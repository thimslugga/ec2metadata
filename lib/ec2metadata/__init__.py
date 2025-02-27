# Copyright (c) 2013 Alon Swartz <alon@turnkeylinux.org>
# Copyright (c) 2019 SUSE LLC
#
# This file is part of ec2metadata.
#
# ec2metadata is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ec2metadata is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ec2metadata.  If not, see <http://www.gnu.org/licenses/>.

import time
import urllib.request
import urllib.parse
import urllib.error
import socket


class EC2MetadataError(Exception):
    pass


class EC2Metadata:
    """Class for querying metadata from EC2"""

    def __init__(self, addr='169.254.169.254', api='2008-02-01'):
        self.addr = addr
        self.api = api
        self.data_categories = ['dynamic/', 'meta-data/']
        self.duplicate_names = []

        if not self._test_connectivity(self.addr, 80):
            msg = 'Could not establish connection to: %s' % self.addr
            raise EC2MetadataError(msg)

        self._set_api_header()
        self._reset_meta_options_api_map()
        self._set_meta_options()

    @staticmethod
    def _test_connectivity(addr, port):
        for i in range(6):
            s = socket.socket()
            try:
                s.connect((addr, port))
                s.close()
                return True
            except socket.error:
                time.sleep(1)

        return False

    def _add_meta_option(self, path):
        """Add meta options available under the current path to the options
           to API map"""
        options = list(self.meta_options_api_map.keys())
        value = self._get(path)
        if not value:
            return None
        entries = value.split('\n')
        for item in entries:
            if item:
                if item == 'public-keys/':
                    continue
                if item[-1] == '/':
                    self._add_meta_option(path+item)
                else:
                    if item not in options and item not in self.duplicate_names:
                        self.meta_options_api_map[item] = path + item
                    else:
                        if item in options:
                            # Expand the existing entry
                            self.duplicate_names.append(item)
                            existing_path = self.meta_options_api_map[item]
                            new_name = self._expand_name(existing_path)
                            self.meta_options_api_map[new_name] = existing_path
                            del(self.meta_options_api_map[item])
                        # Construct a new name for the option using the given
                        # path as name addition
                        option_name = self._expand_name(path, item)
                        self.meta_options_api_map[option_name] = path + item

    def _expand_name(self, path, endpoint=''):
        """Expand the name of an endpoint with the preceeding entry in the
           path or construct the name from the path by using the last to
           elements"""
        path_elements = path.split('/')
        if not path_elements[-1]:
            path_elements = path_elements[:-1]
        if endpoint:
            return path_elements[-1] + '-' + endpoint

        return '-'.join(path_elements[-2:])

    def _get(self, uri):
        url = 'http://%s/%s/%s' % (self.addr, self.api, uri)
        data_request = None
        value = b''
        data_request = urllib.request.Request(url, headers=self.request_header)
        try:
            value = urllib.request.urlopen(data_request).read()
        except urllib.error.URLError:
            return None

        return value.decode()

    def _reset_meta_options_api_map(self):
        """Set options that have special semantics"""
        self.meta_options_api_map = {
            'public-keys': 'meta-data/public-keys',
            'user-data': 'user-data'
        }

    def _set_api_header(self):
        """Set the header to be used in requests to the metadata service,
           IMDs. Prefer IMDSv2 which requires a token."""
        request = urllib.request.Request(
            'http://169.254.169.254/latest/api/token',
            headers={'X-aws-ec2-metadata-token-ttl-seconds': '21600'},
            method='PUT'
        )
        try:
            token = urllib.request.urlopen(request).read().decode()
            self.request_header = {'X-aws-ec2-metadata-token': token}
        except urllib.error.URLError:
            self.request_header = {}
        
    def _set_meta_options(self):
        """Set the metadata options for the current API on this object."""
        for path in self.data_categories:
            self._add_meta_option(path)

    def get(self, metaopt):
        """Return value of metaopt"""

        path = self.meta_options_api_map.get(metaopt, None)
        if not path:
            raise EC2MetadataError('Unknown metaopt: %s' % metaopt)

        if metaopt == 'public-keys':
            public_keys = []
            data = self._get('meta-data/public-keys')
            if not data:
                return public_keys

            keyids = [line.split('=')[0] for line in data.splitlines()]
            for keyid in keyids:
                uri = 'meta-data/public-keys/%d/openssh-key' % int(keyid)
                public_keys.append(self._get(uri).rstrip())

            return public_keys

        return self._get(path)

    def get_available_api_versions(self):
        """Return a list of the available API versions"""
        url = 'http://%s/' % self.addr
        req = urllib.request.Request(url, headers=self.request_header)
        value = urllib.request.urlopen(req).read().decode()
        apiVers = value.split('\n')
        return apiVers

    def get_meta_data_options(self):
        """Return the available options for the current api version"""
        options = list(self.meta_options_api_map.keys())
        options.sort()
        return options

    def set_api_version(self, api_version=None):
        """Set the API version to use for the query"""
        if not api_version:
            # Nothing to do
            return self.api
        url = 'http://%s' % self.addr
        req = urllib.request.Request(url, headers=self.request_header)
        meta_apis = urllib.request.urlopen(req).read().decode().split('\n')
        if api_version not in meta_apis:
            msg = 'Requested API version "%s" not available' % api_version
            raise EC2MetadataError(msg)
        self.api = api_version
        self._reset_meta_options_api_map()
        self._set_meta_options()

    def use_token_access(self):
        """Use token based access to retrieve the metadata information. This
           supports IMDSv2"""
        self.token_access = True
