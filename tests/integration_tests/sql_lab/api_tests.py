# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
# isort:skip_file
"""Unit tests for Superset"""
import datetime
import json
import random

import pytest
import prison
from sqlalchemy.sql import func
from unittest import mock

from tests.integration_tests.test_app import app
from superset import sql_lab
from superset.common.db_query_status import QueryStatus
from superset.models.core import Database
from superset.utils.database import get_example_database, get_main_database
from superset.utils import core as utils
from superset.models.sql_lab import Query

from tests.integration_tests.base_tests import SupersetTestCase

QUERIES_FIXTURE_COUNT = 10


class TestSqlLabApi(SupersetTestCase):
    @mock.patch("superset.sqllab.commands.results.results_backend_use_msgpack", False)
    def test_execute_required_params(self):
        self.login()
        client_id = "{}".format(random.getrandbits(64))[:10]

        data = {"client_id": client_id}
        rv = self.client.post(
            "/api/v1/sqllab/execute/",
            json=data,
        )
        failed_resp = {
            "message": {
                "sql": ["Missing data for required field."],
                "database_id": ["Missing data for required field."],
            }
        }
        resp_data = json.loads(rv.data.decode("utf-8"))
        self.assertDictEqual(resp_data, failed_resp)
        self.assertEqual(rv.status_code, 400)

        data = {"sql": "SELECT 1", "client_id": client_id}
        rv = self.client.post(
            "/api/v1/sqllab/execute/",
            json=data,
        )
        failed_resp = {"message": {"database_id": ["Missing data for required field."]}}
        resp_data = json.loads(rv.data.decode("utf-8"))
        self.assertDictEqual(resp_data, failed_resp)
        self.assertEqual(rv.status_code, 400)

        data = {"database_id": 1, "client_id": client_id}
        rv = self.client.post(
            "/api/v1/sqllab/execute/",
            json=data,
        )
        failed_resp = {"message": {"sql": ["Missing data for required field."]}}
        resp_data = json.loads(rv.data.decode("utf-8"))
        self.assertDictEqual(resp_data, failed_resp)
        self.assertEqual(rv.status_code, 400)

    @mock.patch("superset.sqllab.commands.results.results_backend_use_msgpack", False)
    def test_execute_valid_request(self) -> None:
        from superset import sql_lab as core

        core.results_backend = mock.Mock()
        core.results_backend.get.return_value = {}

        self.login()
        client_id = "{}".format(random.getrandbits(64))[:10]

        data = {"sql": "SELECT 1", "database_id": 1, "client_id": client_id}
        rv = self.client.post(
            "/api/v1/sqllab/execute/",
            json=data,
        )
        resp_data = json.loads(rv.data.decode("utf-8"))
        self.assertEqual(resp_data.get("status"), "success")
        self.assertEqual(rv.status_code, 200)

    @mock.patch(
        "tests.integration_tests.superset_test_custom_template_processors.datetime"
    )
    @mock.patch("superset.sqllab.api.get_sql_results")
    def test_execute_custom_templated(self, sql_lab_mock, mock_dt) -> None:
        mock_dt.utcnow = mock.Mock(return_value=datetime.datetime(1970, 1, 1))
        self.login()
        sql = "SELECT '$DATE()' as test"
        resp = {
            "status": QueryStatus.SUCCESS,
            "query": {"rows": 1},
            "data": [{"test": "'1970-01-01'"}],
        }
        sql_lab_mock.return_value = resp

        dbobj = self.create_fake_db_for_macros()
        json_payload = dict(database_id=dbobj.id, sql=sql)
        self.get_json_resp(
            "/api/v1/sqllab/execute/", raise_on_error=False, json_=json_payload
        )
        assert sql_lab_mock.called
        self.assertEqual(sql_lab_mock.call_args[0][1], "SELECT '1970-01-01' as test")

        self.delete_fake_db_for_macros()

    @mock.patch("superset.sqllab.commands.results.results_backend_use_msgpack", False)
    def test_get_results_with_display_limit(self):
        from superset.sqllab.commands import results as command

        command.results_backend = mock.Mock()
        self.login()

        data = [{"col_0": i} for i in range(100)]
        payload = {
            "status": QueryStatus.SUCCESS,
            "query": {"rows": 100},
            "data": data,
        }
        # limit results to 1
        expected_key = {"status": "success", "query": {"rows": 100}, "data": data}
        limited_data = data[:1]
        expected_limited = {
            "status": "success",
            "query": {"rows": 100},
            "data": limited_data,
            "displayLimitReached": True,
        }

        query_mock = mock.Mock()
        query_mock.sql = "SELECT *"
        query_mock.database = 1
        query_mock.schema = "superset"

        # do not apply msgpack serialization
        use_msgpack = app.config["RESULTS_BACKEND_USE_MSGPACK"]
        app.config["RESULTS_BACKEND_USE_MSGPACK"] = False
        serialized_payload = sql_lab._serialize_payload(payload, False)
        compressed = utils.zlib_compress(serialized_payload)
        command.results_backend.get.return_value = compressed

        with mock.patch("superset.sqllab.commands.results.db") as mock_superset_db:
            mock_superset_db.session.query().filter_by().one_or_none.return_value = (
                query_mock
            )
            # get all results
            arguments = {"key": "key"}
            result_key = json.loads(
                self.get_resp(f"/api/v1/sqllab/results/?q={prison.dumps(arguments)}")
            )
            arguments = {"key": "key", "rows": 1}
            result_limited = json.loads(
                self.get_resp(f"/api/v1/sqllab/results/?q={prison.dumps(arguments)}")
            )

        self.assertEqual(result_key, expected_key)
        self.assertEqual(result_limited, expected_limited)

        app.config["RESULTS_BACKEND_USE_MSGPACK"] = use_msgpack
