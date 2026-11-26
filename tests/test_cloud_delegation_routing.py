"""Saved cloud preferences and asynchronous native CLI delegation API contracts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from harness2 import routing_policy as policy, mcp_server as c, mcp_workflow as w, agent_delegation as agents
from integrations import cad_gateway_harness2 as bridge

class CloudDelegationRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        config=Path(self.temp.name)/"routing.json"
        config.write_text(json.dumps({"default_profile":"ollama_glm_cloud","cloud_authorized":True,"prefer_subscriptions":True,"max_parallel":2}))
        patcher=patch.object(policy,"POLICY_PATH",config)
        patcher.start();self.addCleanup(patcher.stop)

    def test_default_rf_uses_cloud_without_local_model_dependency(self):
        with patch.object(c,"rf_local_profile",side_effect=AssertionError("local model must not be consulted")),patch.object(c,"_start_job",return_value={}) as launch:
            c.harness2_start_rf_run()
        self.assertEqual(launch.call_args.args[1]["profile"],"ollama_glm_cloud")
        self.assertTrue(launch.call_args.args[1]["allow_cloud"])

    def test_default_plan_uses_configured_profile(self):
        with patch.object(w,"plan",return_value={}) as plan:
            c.harness2_plan_run()
        self.assertEqual(plan.call_args.args[0]["profile"],"ollama_glm_cloud")

    def test_delegation_compat_domain_returns_async_job(self):
        blueprint={"roles":[{"role":r} for r in ("planner","implementer","reviewer")]}
        with patch.object(agents,"plan",return_value=blueprint),patch.object(agents,"run",side_effect=AssertionError("MCP call must not block on role inference")),patch.object(c,"_start_job",return_value={"run_id":"x"}) as launch:
            result=c.harness2_start_run(domain="agent_delegation",capability_query="Review routing",workers=2,seconds=180)
        self.assertEqual(result["run_id"],"x")
        self.assertEqual(launch.call_args.args[0],"agent_delegation")
        self.assertEqual(launch.call_args.args[1]["max_parallel"],2)
        self.assertEqual(launch.call_args.args[1]["roles"],["planner","implementer","reviewer"])

    def test_explicit_cloud_denial_blocks_subscription_delegation(self):
        with patch.object(c,"_start_job") as launch,self.assertRaises(ValueError):
            c.harness2_start_run(domain="agent_delegation",capability_query="Review routing",allow_cloud=False)
        launch.assert_not_called()

    def test_compat_domain_rejects_fake_recursion_and_multiple_parent_tasks(self):
        for changes in ({"k":2},{"max_tasks":2},{"workers":True},{"seconds":601}):
            with self.assertRaises(ValueError):
                c.harness2_plan_run(domain="agent_delegation",capability_query="Task",**changes)

    def test_result_exposes_agent_report_without_rf_qualification(self):
        with tempfile.TemporaryDirectory() as td,patch.object(c,"RUNS",Path(td)):
            rid="c"*32
            path=Path(td)/rid/"workflow";path.mkdir(parents=True)
            c._write(rid,{"run_id":rid,"kind":"agent_delegation","state":"succeeded"})
            (path/"workflow.json").write_text(json.dumps({"kind":"agent_delegation","roles":[],"engineering_validation_performed":False}))
            result=c.harness2_results(rid)
        self.assertIn("agent_delegation",result)
        self.assertNotIn("rf_workflow",result)

    def test_bridge_preserves_omitted_route_arguments(self):
        with patch.object(bridge,"_call",return_value={}) as call:
            bridge.harness2_start_rf_run()
        self.assertIsNone(call.call_args.args[1]["allow_cloud"])

if __name__=="__main__":
    unittest.main()
