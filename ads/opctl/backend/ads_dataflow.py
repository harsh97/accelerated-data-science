#!/usr/bin/env python
# -*- coding: utf-8; -*-

# Copyright (c) 2022, 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/


import os
import json
import shlex
from typing import Dict, Union

from ads.opctl.backend.base import Backend
from ads.common.auth import create_signer, AuthContext
from ads.common.oci_client import OCIClientFactory

from ads.opctl.backend.base import (
    Backend,
    RuntimeFactory,
)

from ads.jobs import (
    Job,
    DataFlow,
    DataFlowRuntime,
    DataFlowNotebookRuntime,
    DataFlowRun,
)

REQUIRED_FIELDS = [
    "compartment_id",
    "driver_shape",
    "executor_shape",
    "logs_bucket_uri",
    "script_bucket",
]


class DataFlowBackend(Backend):
    def __init__(self, config: Dict) -> None:
        """
        Initialize a MLJobBackend object given config dictionary.

        Parameters
        ----------
        config: dict
            dictionary of configurations
        """
        self.config = config
        self.oci_auth = create_signer(
            config["execution"].get("auth"),
            config["execution"].get("oci_config", None),
            config["execution"].get("oci_profile", None),
        )
        self.auth_type = config["execution"].get("auth")
        self.profile = config["execution"].get("oci_profile", None)
        self.client = OCIClientFactory(**self.oci_auth).dataflow

    def init(
        self,
        uri: Union[str, None] = None,
        overwrite: bool = False,
        runtime_type: Union[str, None] = None,
        **kwargs: Dict,
    ) -> Union[str, None]:
        """Generates a starter YAML specification for a Data Flow Application.

        Parameters
        ----------
        overwrite: (bool, optional). Defaults to False.
            Overwrites the result specification YAML if exists.
        uri: (str, optional), Defaults to None.
            The filename to save the resulting specification template YAML.
        runtime_type: (str, optional). Defaults to None.
                The resource runtime type.
        **kwargs: Dict
            The optional arguments.

        Returns
        -------
        Union[str, None]
            The YAML specification for the given resource if `uri` was not provided.
            `None` otherwise.
        """

        with AuthContext(auth=self.auth_type, profile=self.profile):
            # define an job
            job = (
                Job()
                .with_name(
                    "{Job name. For MLflow, it will be replaced with the Project name}"
                )
                .with_infrastructure(
                    DataFlow(**(self.config.get("infrastructure", {}) or {})).init()
                )
                .with_runtime(
                    DataFlowRuntimeFactory.get_runtime(
                        key=runtime_type or DataFlowRuntime().type
                    ).init()
                )
            )

            note = (
                "# This YAML specification was auto generated by the `ads opctl init` command.\n"
                "# The more details about the jobs YAML specification can be found in the ADS documentation:\n"
                "# https://accelerated-data-science.readthedocs.io/en/latest/user_guide/apachespark/dataflow.html \n\n"
            )

            return job.to_yaml(
                uri=uri,
                overwrite=overwrite,
                note=note,
                filter_by_attribute_map=True,
                **kwargs,
            )

    def apply(self):
        """
        Create DataFlow and DataFlow Run from YAML.
        """
        # TODO add the logic for build dataflow and dataflow run from YAML.
        raise NotImplementedError(f"`apply` hasn't been supported for data flow yet.")

    def run(self) -> None:
        """
        Create DataFlow and DataFlow Run from OCID or cli parameters.
        """
        with AuthContext(auth=self.auth_type, profile=self.profile):
            if self.config["execution"].get("ocid", None):
                data_flow_id = self.config["execution"]["ocid"]
                run_id = Job.from_dataflow_job(data_flow_id).run().id
            else:
                infra = self.config.get("infrastructure", {})
                if any(k not in infra for k in REQUIRED_FIELDS):
                    missing = [k for k in REQUIRED_FIELDS if k not in infra]
                    raise ValueError(
                        f"Following fields are missing but are required for OCI DataFlow Jobs: {missing}. Please run `ads opctl configure`."
                    )
                rt_spec = {}
                rt_spec["scriptPathURI"] = os.path.join(
                    self.config["execution"]["source_folder"],
                    self.config["execution"]["entrypoint"],
                )
                if "script_bucket" in infra:
                    rt_spec["scriptBucket"] = infra.pop("script_bucket")
                if self.config["execution"].get("command"):
                    rt_spec["args"] = shlex.split(self.config["execution"]["command"])
                if self.config["execution"].get("archive"):
                    rt_spec["archiveUri"] = self.config["execution"]["archive"]
                    rt_spec["archiveBucket"] = infra.pop("archive_bucket", None)
                rt = DataFlowRuntime(rt_spec)
                if "configuration" in infra:
                    infra["configuration"] = json.loads(infra["configuration"])
                df = Job(infrastructure=DataFlow(spec=infra), runtime=rt)
                df.create(overwrite=self.config["execution"].get("overwrite", False))
                job_id = df.id
                run_id = df.run().id
        print("DataFlow App ID:", job_id)
        print("DataFlow Run ID:", run_id)
        return {"job_id": job_id, "run_id": run_id}

    def cancel(self):
        """
        Cancel DataFlow Run from OCID.
        """
        if not self.config["execution"].get("run_id"):
            raise ValueError("Can only cancel a DataFlow run.")
        run_id = self.config["execution"]["run_id"]
        with AuthContext(auth=self.auth_type, profile=self.profile):
            DataFlowRun.from_ocid(run_id).delete()

    def delete(self):
        """
        Delete DataFlow or DataFlow Run from OCID.
        """
        if self.config["execution"].get("id"):
            data_flow_id = self.config["execution"]["id"]
            with AuthContext(auth=self.auth_type, profile=self.profile):
                Job.from_dataflow_job(data_flow_id).delete()
        elif self.config["execution"].get("run_id"):
            run_id = self.config["execution"]["run_id"]
            with AuthContext(auth=self.auth_type, profile=self.profile):
                DataFlowRun.from_ocid(run_id).delete()

    def watch(self):
        """
        Watch DataFlow Run from OCID.
        """
        run_id = self.config["execution"]["run_id"]
        with AuthContext(auth=self.auth_type, profile=self.profile):
            run = DataFlowRun.from_ocid(run_id)
            run.watch()


class DataFlowRuntimeFactory(RuntimeFactory):
    """Data Flow runtime factory."""

    _MAP = {
        DataFlowRuntime().type: DataFlowRuntime,
        DataFlowNotebookRuntime().type: DataFlowNotebookRuntime,
    }
