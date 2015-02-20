# Copyright (c) 2014 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from boto.s3.connection import S3Connection, OrdinaryCallingFormat

RETRY_COUNT = 3


class Connection(object):
    """
    Manage Connection
    """
    def __init__(self, aws_access_key=None, aws_secret_key=None):
        """
        Make S3Connection
        """
        self.conn = None
        self.aws_access_key = aws_access_key
        self.aws_secret_key = aws_secret_key
        self.user_id = None
        swift_host = os.environ.get('SWIFT_HOST').split(':')
        self.host = swift_host[0]
        self.port = int(swift_host[1]) if len(swift_host) == 2 else 80

    def set_admin(self):
        """
        Set Admin user key
        """
        self.aws_access_key = os.environ.get('ADMIN_ACCESS_KEY')
        self.aws_secret_key = os.environ.get('ADMIN_SECRET_KEY')
        self.user_id = os.environ.get('ADMIN_TENANT') + ':' + \
            os.environ.get('ADMIN_USER')

    def set_tester1(self):
        """
        Set Tester1 user key
        """
        self.aws_access_key = os.environ.get('TESTER_ACCESS_KEY')
        self.aws_secret_key = os.environ.get('TESTER_SECRET_KEY')
        self.user_id = os.environ.get('TESTER_TENANT') + ':' + \
            os.environ.get('TESTER_USER')

    def set_tester2(self):
        """
        Set Tester2 user key
        """
        self.aws_access_key = os.environ.get('TESTER2_ACCESS_KEY')
        self.aws_secret_key = os.environ.get('TESTER2_SECRET_KEY')
        self.user_id = os.environ.get('TESTER2_TENANT') + ':' + \
            os.environ.get('TESTER2_USER')

    def connect(self):
        return S3Connection(self.aws_access_key, self.aws_secret_key,
                            is_secure=False, host=self.host, port=self.port,
                            calling_format=OrdinaryCallingFormat())

    def make_request(self, method, bucket='', obj='', headers=None, body='',
                     query=None):
        conn = self.connect()
        response = \
            conn.make_request(method, bucket=bucket, key=obj,
                              headers=headers, data=body,
                              query_args=query, sender=None,
                              override_num_retries=RETRY_COUNT,
                              retry_handler=None)
        return response.status, dict(response.getheaders()), response.read()
