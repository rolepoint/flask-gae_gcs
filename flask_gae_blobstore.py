"""
  flask_gae_cloud_storage
  ~~~~~~~~~~~~~~~~~~~

  Flask extension for working with Google Cloud Storage on
  Google App Engine.

  :copyright: (c) 2013 by gregorynicholas.
  :license: BSD, see LICENSE for more details.
"""
import re
import time
import uuid
import string
import random
import logging
import cloudstorage as gcs
from flask import Response, request
from werkzeug import exceptions
from functools import wraps
from google.appengine.api import files, app_identity
from google.appengine.ext import blobstore
from google.appengine.ext.blobstore import BlobKey, create_rpc

__all__ = [
    'delete', 'delete_async', 'fetch_data', 'fetch_data_async', 'BlobKey',
    'WRITE_MAX_RETRIES', 'WRITE_SLEEP_SECONDS', 'DEFAULT_NAME_LEN',
    'MSG_INVALID_FILE_POSTED', 'UPLOAD_MIN_FILE_SIZE', 'UPLOAD_MAX_FILE_SIZE',
    'UPLOAD_ACCEPT_FILE_TYPES', 'ORIGINS', 'OPTIONS', 'HEADERS', 'MIMETYPE',
    'RemoteResponse', 'BlobUploadResultSet', 'BlobUploadResult', 'upload_blobs',
    'save_blobs', 'write_to_blobstore']

delete = blobstore.delete
delete_async = blobstore.delete_async
fetch_data = blobstore.fetch_data
fetch_data_async = blobstore.fetch_data_async

#:
WRITE_MAX_RETRIES = 3
#:
WRITE_SLEEP_SECONDS = 0.05
#:
DEFAULT_NAME_LEN = 20
#:
MSG_INVALID_FILE_POSTED = 'Invalid file posted.'

#:
UPLOAD_MIN_FILE_SIZE = 1
#:
UPLOAD_MAX_FILE_SIZE = 1024 * 1024
# set by default to images..
#:
UPLOAD_ACCEPT_FILE_TYPES = re.compile('image/(gif|p?jpeg|jpg|(x-)?png|tiff)')

# todo: need a way to easily configure these values..
#:
ORIGINS = '*'
#:
OPTIONS = ['OPTIONS', 'HEAD', 'GET', 'POST', 'PUT']
#:
HEADERS = ['Accept', 'Content-Type', 'Origin', 'X-Requested-With']
#:
MIMETYPE = 'application/json'

my_default_retry_params = gcs.RetryParams(initial_delay=0.2,
                                          max_delay=5.0,
                                          backoff_factor=2,
                                          max_retry_period=15)


class RemoteResponse(Response):

    '''Base class for remote service `Response` objects.

      :param response:
      :param mimetype:
    '''
    default_mimetype = MIMETYPE

    def __init__(self, response=None, mimetype=None, *args, **kw):
        if mimetype is None:
            mimetype = self.default_mimetype
        Response.__init__(self, response=response, mimetype=mimetype, **kw)
        self._fixcors()

    def _fixcors(self):
        self.headers['Access-Control-Allow-Origin'] = ORIGINS
        self.headers['Access-Control-Allow-Methods'] = ', '.join(OPTIONS)
        self.headers['Access-Control-Allow-Headers'] = ', '.join(HEADERS)


class BlobUploadResultSet(list):

    def to_dict(self):
        '''
          :returns: List of `BlobUploadResult` as `dict`s.
        '''
        result = []
        for field in self:
            result.append(field.to_dict())
        return result


class BlobUploadResult:

    '''
      :param successful:
      :param error_msg:
      :param uuid:
      :param name:
      :param type:
      :param size:
      :param field:
      :param value:
    '''

    def __init__(self, name, type, size, field, value):
        self.successful = False
        self.error_msg = ''
        self.uuid = None
        self.name = name
        self.type = type
        self.size = size
        self.field = field
        self.value = value

    @property
    def blob_info(self):
        return blobstore.get(self.blob_key)

    def to_dict(self):
        '''
          :returns: Instance of a dict.
        '''
        return {
            'successful': self.successful,
            'error_msg': self.error_msg,
            'uuid': str(self.uuid),
            'name': self.name,
            'type': self.type,
            'size': self.size,
            # these two are commented out so the class is easily json serializable..
            # 'field': self.field,
            # 'value': self.value,
        }


def upload_blobs(validators=None):
    '''Method decorator for writing posted files to the `blobstore` using the
    App Engine files api. Passes an argument to the method with a list of
    `BlobUploadResult` with `BlobKey`, name, type, size for each posted input file.

      :param validators: List of callable objects.
    '''
    def wrapper(fn):
        @wraps(fn)
        def decorated(*args, **kw):
            return fn(uploads=save_blobs(
                      fields=_upload_fields(), validators=validators), *args, **kw)
        return decorated
    return wrapper


def save_blobs(fields, validators=None):
    '''Returns a list of `BlobUploadResult` with BlobKey, name, type, size for
    each posted file.

      :param fields: List of `cgi.FieldStorage` objects.
      :param validators: List of callable objects.

      :returns: Instance of a `BlobUploadResultSet`.
    '''

    if validators is None:
        validators = [
            validate_min_size,
            # validate_file_type,
            # validate_max_size,
        ]
    results = BlobUploadResultSet()
    i = 0
    for name, field in fields:
        value = field.stream.read()
        filename = re.sub(r'^.*\\', '', field.filename.decode('utf-8'))
        result = BlobUploadResult(
            name=filename,
            type=field.mimetype,
            size=len(value),
            field=field,
            value=value)
        if validators:
            for fn in validators:
                if not fn(result):
                    result.successful = False
                    result.error_msg = MSG_INVALID_FILE_POSTED
                    logging.warn('Error in file upload: %s', result.error_msg)
                else:
                    result.uuid = write_to_gcs(
                        result.value, mime_type=result.type, name=result.name)
                    if result.uuid:
                        result.successful = True
                    else:
                        result.successful = False
            results.append(result)
        else:
            result.uuid = write_to_gcs(
                result.value, mime_type=result.type, name=result.name)
            logging.error('result.uuid: %s', result.uuid)
            if result.uuid:
                result.successful = True
            else:
                result.successful = False
            results.append(result)
        i += 1
    return results


def _upload_fields():
    '''
      :returns: List of tuples with the filename & `cgi.FieldStorage` as value.
    '''
    result = []
    for key, value in request.files.iteritems():
        if not isinstance(value, unicode):
            result.append((key, value))
    return result


def get_field_size(field):
    '''
      :param field: Instance of `cgi.FieldStorage`.
      :returns: Integer.
    '''
    try:
        field.seek(0, 2)  # Seek to the end of the file
        size = field.tell()  # Get the position of EOF
        field.seek(0)  # Reset the file position to the beginning
        return size
    except:
        return 0


def validate_max_size(result, max_file_size=UPLOAD_MAX_FILE_SIZE):
    '''Validates an upload input based on maximum size.

      :param result: Instance of `BlobUploadResult`.
      :param max_file_size: Integer.
      :returns: Boolean, True if field validates.
    '''
    if result.size > max_file_size:
        result.error_msg = 'max_file_size'
        return False
    return True


def validate_min_size(result, min_file_size=UPLOAD_MIN_FILE_SIZE):
    '''Validates an upload input based on minimum size.

      :param result: Instance of `BlobUploadResult`.
      :param min_file_size: Integer.
      :returns: Boolean, True if field validates.
    '''
    if result.size < min_file_size:
        result.error_msg = 'min_file_size'
        return False
    return True


def validate_file_type(result, accept_file_types=UPLOAD_ACCEPT_FILE_TYPES):
    '''Validates an upload input based on accepted mime types.
    If validation fails, sets an error property to the field arg dict.

      :param result: Instance of `BlobUploadResult`.
      :param accept_file_types: Instance of a regex.
      :returns: Boolean, True if field validates.
    '''
    # only allow images to be posted to this handler
    if not accept_file_types.match(result.type):
        result.field.error_msg = 'accept_file_types'
        return False
    return True


def write_to_gcs(data, mime_type, name=None):
    '''Writes a file to Google Cloud Storage and returns the file name
    if successful.

      :param data: Data to be stored.
      :param mime_type: String, mime type of the data.
      :param name: String, name of the data.

      :returns: String, filename.
    '''
    if not name:
        name = ''.join(random.choice(string.letters)
                       for x in range(DEFAULT_NAME_LEN))

    bucket_name = app_identity.get_default_gcs_bucket_name()

    resume_uuid = uuid.uuid4()
    bucket_filename = '/' + bucket_name + '/' + str(resume_uuid)

    write_retry_params = gcs.RetryParams(backoff_factor=1.1)
    gcs_file = gcs.open(bucket_filename,
                        'w',
                        content_type=mime_type,
                        options = {
                            'x-goog-meta-filename': name,
                            'Content-Disposition': 'attachment; filename={}'
                                .format(name)
                        },
                        retry_params=write_retry_params)

    gcs_file.write(data)
    gcs_file.close()

    return str(resume_uuid)


def send_blob_download():
    '''Sends a file to a client for downloading.

      :param data: Stream data that will be sent as the file contents.
      :param filename: String, name of the file.
      :param contenttype: String, content-type of the file.
    '''
    def wrapper(fn):
        @wraps(fn)
        def decorated(*args, **kw):
            data, filename, contenttype = fn(*args, **kw)
            headers = {
                'Content-Type': contenttype,
                'Content-Encoding': contenttype,
                'Content-Disposition': 'attachment; filename={}'.format(filename)}
            return Response(data, headers=headers)
        return decorated
    return wrapper
