"""
  flask_gae_gcs
  ~~~~~~~~~~~~~~~~~~~

  Flask extension for working with Google Cloud Storage on
  Google App Engine.

  :license: BSD, see LICENSE for more details.
"""
import re
import uuid
import string
import random
import logging
import cloudstorage as gcs
from flask import Response, request
from functools import wraps
from google.appengine.api import app_identity

__all__ = [
    'WRITE_MAX_RETRIES', 'WRITE_SLEEP_SECONDS', 'DEFAULT_NAME_LEN',
    'MSG_INVALID_FILE_POSTED', 'UPLOAD_MIN_FILE_SIZE', 'UPLOAD_MAX_FILE_SIZE',
    'UPLOAD_ACCEPT_FILE_TYPES', 'ORIGINS', 'OPTIONS', 'HEADERS', 'MIMETYPE',
    'RemoteResponse', 'FileUploadResultSet', 'FileUploadResult',
    'upload_files', 'save_files', 'write_to_gcs']

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


class FileUploadResultSet(list):

    def to_dict(self):
        '''
          :returns: List of `FileUploadResult` as `dict`s.
        '''
        result = []
        for field in self:
            result.append(field.to_dict())
        return result


class FileUploadResult:

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

    def __init__(self, name, type, size, field, value, bucket_name):
        self.successful = False
        self.error_msg = ''
        self.uuid = None
        self.name = name
        self.type = type
        self.size = size
        self.field = field
        self.value = value
        self.bucket_name = None

    @property
    def file_info(self):
        return gcs.stat(get_gcs_filename(self.uuid, self.bucket_name))

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
            'size': self.size
        }


def get_gcs_filename(filename, bucket_name=None):
    if bucket_name:
        return '/' + bucket_name + '/' + filename
    return '/' + app_identity.get_default_gcs_bucket_name() + '/' + filename


def upload_files(validators=None, retry_params=None, bucket_name=None):
    '''Method decorator for writing posted files to Google Cloud Storage using
    the App Engine CloudStorage api. Passes an argument to the method with a
    list of `FileUploadResult` with UUID, name, type, size for each posted
    input file.

      :param validators: List of callable objects.
      :param retry_params: `RetryParams` object from `cloudstorage`
      :param bucket_name: String of custom bucket name.
    '''
    def wrapper(fn):
        @wraps(fn)
        def decorated(*args, **kw):
            return fn(uploads=save_files(
                          fields=_upload_fields(),
                          validators=validators,
                          retry_params=retry_params,
                          bucket_name=bucket_name
                          ), *args, **kw)
        return decorated
    return wrapper


def save_files(fields, validators=None, retry_params=None, bucket_name=None):
    '''Returns a list of `FileUploadResult` with UUID, name, type, size for
    each posted file.

      :param fields: List of `cgi.FieldStorage` objects.
      :param validators: List of functions, usually one of validate_min_size,
                         validate_file_type, validate_max_size included here.
                         By default validate_min_size is included to make sure
                         the file is not empty (see UPLOAD_MIN_FILE_SIZE).
      :param retry_params: `RetryParams` object from `cloudstorage`
      :param bucket_name: String of custom bucket name.

      :returns: Instance of a `FileUploadResultSet`.
    '''

    if validators is None:
        validators = [
            validate_min_size
        ]
    results = FileUploadResultSet()
    i = 0
    for name, field in fields:
        value = field.stream.read()
        filename = re.sub(r'^.*\\', '', field.filename)
        result = FileUploadResult(
            name=filename,
            type=field.mimetype,
            size=len(value),
            field=field,
            value=value,
            bucket_name=bucket_name if bucket_name else None)
        if validators:
            for fn in validators:
                if not fn(result):
                    result.successful = False
                    result.error_msg = MSG_INVALID_FILE_POSTED
                    logging.warn('Error in file upload: %s', result.error_msg)
                else:
                    result.uuid = write_to_gcs(
                        result.value, mime_type=result.type, name=result.name,
                        retry_params=retry_params, bucket_name=bucket_name)
                    if result.uuid:
                        result.successful = True
                    else:
                        result.successful = False
            results.append(result)
        else:
            result.uuid = write_to_gcs(
                result.value, mime_type=result.type, name=result.name,
                retry_params=retry_params, bucket_name=bucket_name)
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

      :param result: Instance of `FileUploadResult`.
      :param max_file_size: Integer.
      :returns: Boolean, True if field validates.
    '''
    if result.size > max_file_size:
        result.error_msg = 'max_file_size'
        return False
    return True


def validate_min_size(result, min_file_size=UPLOAD_MIN_FILE_SIZE):
    '''Validates an upload input based on minimum size.

      :param result: Instance of `FileUploadResult`.
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

      :param result: Instance of `FileUploadResult`.
      :param accept_file_types: Instance of a regex.

      :returns: Boolean, True if field validates.
    '''
    # only allow images to be posted to this handler
    if not accept_file_types.match(result.type):
        result.field.error_msg = 'accept_file_types'
        return False
    return True


def write_to_gcs(data, mime_type, name=None, retry_params=None,
                 bucket_name=None, force_download=False):
    '''Writes a file to Google Cloud Storage and returns the file name
    if successful.

      :param data: Data to be stored.
      :param mime_type: String, mime type of the data.
      :param name: String, name of the data.
      :param retry_params: `RetryParams` object from `cloudstorage`
      :param bucket_name: String of custom bucket name.
      :param force_download: Boolean, whether or not file will be a forced
                             download

      :returns: String, filename.
    '''
    if not name:
        name = ''.join(random.choice(string.letters)
                       for x in range(DEFAULT_NAME_LEN))

    new_uuid = str(uuid.uuid4())
    bucket_filename = get_gcs_filename(new_uuid, bucket_name)

    if retry_params:
        default_retry_params = retry_params
    else:
        default_retry_params = gcs.RetryParams(initial_delay=0.2,
                                               max_delay=5.0,
                                               backoff_factor=2,
                                               max_retry_period=15)
    if isinstance(name, unicode):
        name = name.encode('ascii', errors='replace')

    options = {}
    if name:
        options.update({b'x-goog-meta-filename': name})

    if force_download:
        options.update({
            b'Content-Disposition': 'attachment; filename={}'.format(name)
        })

    gcs_file = gcs.open(bucket_filename,
                        'w',
                        content_type=mime_type,
                        options=options,
                        retry_params=default_retry_params)
    gcs_file.write(data)
    gcs_file.close()

    return new_uuid
