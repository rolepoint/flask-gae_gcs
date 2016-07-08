#!/usr/bin/env python
"""
flask-gae_gcs
~~~~~~~~~~~~~~~~~~~

flask extension for working with Google Cloud Storage & Cloudstorage API on
Google App Engine.


links
`````

* `docs <http://siamerp.github.io/flask-gae_gcs>`_
* `source <http://github.com/siamerp/flask-gae_gcs>`

"""
from setuptools import setup

__version__ = "0.2.0"

with open("requirements.txt", "r") as f:
  requires = f.readlines()

with open("README.md", "r") as f:
  long_description = f.readlines()


setup(
  name='flask-gae_gcs',
  version=__version__,
  url='http://github.com/siamerp/flask-gae_blobstore',
  license='MIT',
  author='siamerp',
  author_email='siame@rolepoint.com',
  description=__doc__,
  long_description=long_description,
  py_modules=[
    'flask_gae_gcs',
    'flask_gae_gcs_tests',
  ],
  zip_safe=False,
  platforms='any',
  install_requires=[
    'flask==0.9',
  ],
  tests_require=[
    'flask_gae_tests==1.0.1',
  ],
  dependency_links=[
  ],
  test_suite='flask_gae_gcs_tests',
  classifiers=[
    'Development Status :: 4 - Beta',
    'Environment :: Web Environment',
    'Intended Audience :: Developers',
    'License :: OSI Approved :: MIT License',
    'Operating System :: OS Independent',
    'Programming Language :: Python',
    'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
    'Topic :: Software Development :: Libraries :: Python Modules'
  ]
)
