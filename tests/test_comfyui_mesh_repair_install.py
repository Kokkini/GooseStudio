import unittest

from scripts.install_comfyui_mesh_repair import patch_api_workflow, patch_ui_workflow


class ComfyUIRepairInstallTest(unittest.TestCase):
    def test_patches_api_workflow(self):
        workflow = {
            "43": {"class_type": "Hy3D21PostprocessMesh", "inputs": {"trimesh": ["9", 0]}},
            "45": {"class_type": "Hy3D21MeshUVWrap", "inputs": {"trimesh": ["43", 0]}},
        }

        repair_id = patch_api_workflow(workflow)

        self.assertEqual(repair_id, "46")
        self.assertEqual(workflow[repair_id]["class_type"], "RepairLongEdgeOutliers")
        self.assertEqual(workflow[repair_id]["inputs"]["trimesh"], ["43", 0])
        self.assertEqual(workflow[repair_id]["inputs"]["median_multiplier"], 5.0)
        self.assertEqual(workflow["45"]["inputs"]["trimesh"], ["46", 0])

    def test_patches_ui_workflow_and_is_idempotent(self):
        post = {
            "id": 43,
            "type": "Hy3D21PostprocessMesh",
            "pos": [0, 100],
            "order": 13,
            "inputs": [],
            "outputs": [{"name": "trimesh", "links": [86]}],
        }
        uv = {
            "id": 45,
            "type": "Hy3D21MeshUVWrap",
            "pos": [0, 500],
            "order": 14,
            "inputs": [{"name": "trimesh", "link": 86}],
            "outputs": [],
        }
        workflow = {
            "last_node_id": 45,
            "last_link_id": 86,
            "nodes": [post, uv],
            "links": [[86, 43, 0, 45, 0, "TRIMESH"]],
        }

        patch_ui_workflow(workflow)
        first_links = list(workflow["links"])
        patch_ui_workflow(workflow)

        repairs = [node for node in workflow["nodes"] if node["type"] == "RepairLongEdgeOutliers"]
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["id"], 46)
        self.assertEqual(repairs[0]["order"], 14)
        self.assertEqual(
            [(link[1], link[3]) for link in workflow["links"] if link[1] in (43, 46) or link[3] in (45, 46)],
            [(43, 46), (46, 45)],
        )
        self.assertEqual(len(first_links), 2)
        self.assertEqual(len(workflow["links"]), 2)
        self.assertEqual(next(item["link"] for item in uv["inputs"] if item["name"] == "trimesh"), 90)

    def test_patches_ui_export_branch_as_well_as_uv(self):
        post = {
            "id": 43,
            "type": "Hy3D21PostprocessMesh",
            "pos": [0, 100],
            "order": 13,
            "inputs": [],
            "outputs": [{"name": "trimesh", "links": [86, 87]}],
        }
        uv = {
            "id": 45,
            "type": "Hy3D21MeshUVWrap",
            "pos": [0, 500],
            "order": 14,
            "inputs": [{"name": "trimesh", "link": 86}],
            "outputs": [],
        }
        exporter = {
            "id": 44,
            "type": "Hy3D21ExportMesh",
            "pos": [500, 500],
            "order": 15,
            "inputs": [{"name": "trimesh", "link": 87}],
            "outputs": [],
        }
        workflow = {
            "last_node_id": 45,
            "last_link_id": 87,
            "nodes": [post, uv, exporter],
            "links": [
                [86, 43, 0, 45, 0, "TRIMESH"],
                [87, 43, 0, 44, 0, "TRIMESH"],
            ],
        }

        patch_ui_workflow(workflow)

        repair = next(node for node in workflow["nodes"] if node["type"] == "RepairLongEdgeOutliers")
        destinations = {(link[3], link[4]) for link in workflow["links"] if link[1] == repair["id"]}
        self.assertEqual(destinations, {(45, 0), (44, 0)})
        self.assertEqual(len(repair["outputs"][0]["links"]), 2)


if __name__ == "__main__":
    unittest.main()
