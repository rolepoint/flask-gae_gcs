#!/usr/bin/env python
# coding: utf-8
import uuid
import unittest, logging
from flask import json
from flask import Flask
from flask.ext import gae_tests
from flask.ext import gae_gcs
from google.appengine.ext import ndb
import cloudstorage as gcs

# test application..

class TestModel(ndb.Model):
  test_uuid = ndb.StringProperty()

app = Flask(__name__)
app.debug = True
app.request_class = gae_tests.FileUploadRequest

@app.route('/test_upload', methods=['POST', 'OPTIONS', 'HEAD', 'PUT'])
@gae_gcs.upload_files()
def test_upload(uploads):
  entities = []
  try:
    for upload in uploads:
      entity = TestModel(
        test_uuid=upload.uuid)
      entities.append(entity)
      file_info = upload.file_info
      logging.info('upload.file_info: %s', file_info)
    ndb.put_multi(entities)
  except:
    # rollback the operation and delete the blobs,
    # so they are not orphaned..
    for upload in uploads:
      gcs.delete(gae_gcs.get_gcs_filename(upload.uuid))
    raise Exception('Saving file upload info to datastore failed..')
  return json.dumps(uploads.to_dict())


# test cases..

class TestCase(gae_tests.TestCase):

  def test_blobstore_sanity_check(self):
    test_uuid = str(uuid.uuid4())
    bucket_filename = gae_gcs.get_gcs_filename(test_uuid)
    gcs_file = gcs.open(bucket_filename,
                        'w',
                        content_type='application/octet-stream',
                        options = {
                            'x-goog-meta-filename': 'test_filename'
                        })
    self.assertNotEquals(None, gcs_file)
    gcs_file.write('test blob data..')
    gcs_file.close()
    stats = gcs.stat(bucket_filename)
    self.assertEquals(
        'test_filename', stats.metadata['x-goog-meta-filename']
    )

  def _assertUploadResult(self, result, filename, size):
    self.assertEquals(True, result['successful'])
    # check the file name is the same..
    self.assertEquals(filename, result['name'])
    # check file size is the same..
    self.assertEquals(size, result['size'])
    # validate the uuid..
    self.assertTrue(len(result['uuid']) > 0)

    file_info = gcs.stat(gae_gcs.get_gcs_filename(result['uuid']))
    # check filename is in metadata as well as FileUploadResult
    self.assertEquals(file_info.metadata['x-goog-meta-filename'], filename)
    # check filesize is the same when retrieving information on the file
    self.assertEquals(file_info.st_size, size)

  def test_upload_returns_valid_file_result(self):
    data, filename, size = gae_tests.create_test_file('test.jpg')
    response = app.test_client().post(
      data={'test': (data, filename)},
      path='/test_upload',
      headers={},
      query_string={})
    self.assertEqual(200, response.status_code)
    results = json.loads(response.data)
    self.assertIsInstance(results, list)
    self.assertEquals(1, len(results), results)
    self._assertUploadResult(results[0], filename, size)

  def test_upload_unicode_filename_succeeds(self):
    data, filename, size = gae_tests.create_test_file(filename=u'têst.png')
    response = app.test_client().post(
      data={'test': (data, filename)},
      path='/test_upload',
      headers={},
      query_string={})
    self.assertEqual(200, response.status_code)
    results = json.loads(response.data)
    self.assertIsInstance(results, list)
    self.assertEquals(1, len(results), results)
    self._assertUploadResult(results[0], filename, size)

  def test_multiple_uploads_return_all_results(self):
    testfiles = [gae_tests.create_test_file('test%d.jpg' % x) for x in range(5)]
    tests = {x[0]: (x[0], x[1]) for x in testfiles}
    response = app.test_client().post(
      data=tests,
      path='/test_upload',
      headers={},
      query_string={})
    self.assertEqual(200, response.status_code)
    results = json.loads(response.data)
    self.assertIsInstance(results, list)
    self.assertEquals(len(testfiles), len(results), results)
    for testfile, result in zip(testfiles, results):
        filename = testfile[1]
        size = testfile[2]
        self._assertUploadResult(result, filename, size)

  def test_empty_upload_post_returns_empty_list(self):
    response = app.test_client().post(
      data={'test': ''},
      path='/test_upload',
      headers={},
      query_string={})
    self.assertEqual(200, response.status_code)
    results = json.loads(response.data)
    self.assertIsInstance(results, list)
    self.assertEquals(0, len(results), results)


if __name__ == '__main__':
  unittest.main()
