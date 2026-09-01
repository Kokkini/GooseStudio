import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProjectStructureTest(unittest.TestCase):
    def test_workflow_templates_have_required_nodes(self):
        cases = {
            "qwen-image-edit.json": {"78", "469", "477", "472", "433:111", "433:110", "433:3"},
            "qwen-virtual-try-on.json": {"78", "469", "472", "433:111", "433:3"},
            "wan-character-swap.json": {"159", "160", "301", "360", "368", "548:537"},
            "z-image-turbo.json": {"9", "57:27", "57:13", "57:3", "57:28", "57:30"},
            "image-to-3d.json": {"14", "54", "4", "9", "43", "44", "45", "19", "20", "21", "49", "57"},
        }
        for filename, nodes in cases.items():
            with self.subTest(filename=filename):
                workflow = json.loads((ROOT / "web" / "workflows" / filename).read_text(encoding="utf-8"))
                self.assertTrue(nodes.issubset(workflow))

    def test_browser_owns_workflow_mutations(self):
        source = (ROOT / "web" / "src" / "workflows.ts").read_text(encoding="utf-8")
        for mutation in (
            "workflow['301'].inputs.video",
            "workflow['78'].inputs.image",
            "delete workflow[nodeId]",
            "workflow['433:3'].inputs.seed",
            "workflow['751'].inputs.audio = voice || video",
            "workflow['57:27'].inputs.text",
            "workflow['9'].inputs.filename_prefix",
            "workflow['14'].inputs.image",
            "workflow['57'].inputs.filename_prefix",
        ):
            self.assertIn(mutation, source)

    def test_modal_executor_has_no_workflow_specific_node_ids(self):
        source = (ROOT / "modal" / "goose_studio_executor.py").read_text(encoding="utf-8")
        for node_id in ("548:537", 'workflow["301"]', 'workflow["433:3"]'):
            self.assertNotIn(node_id, source)

    def test_allowed_node_classes_match_bundled_workflows(self):
        expected = set()
        for path in (ROOT / "web" / "workflows").glob("*.json"):
            expected.update(
                node["class_type"]
                for node in json.loads(path.read_text(encoding="utf-8")).values()
            )
        lite = json.loads((ROOT / "assets" / "lite-workflow.json").read_text(encoding="utf-8"))
        expected.update(node["class_type"] for node in lite.values())
        actual = set(
            json.loads((ROOT / "assets" / "allowed-node-classes.json").read_text(encoding="utf-8"))
        )
        self.assertEqual(expected, actual)

    def test_setup_accepts_complete_modal_token_command(self):
        source = (ROOT / "web" / "src" / "tokenCommand.ts").read_text(encoding="utf-8")
        self.assertIn("--token-id", source)
        self.assertIn("--token-secret", source)
        self.assertIn("--profile", source)
        dialog = (ROOT / "web" / "src" / "components" / "SetupDialog.tsx").read_text(encoding="utf-8")
        self.assertIn("modal token set", dialog)
        self.assertIn("https://modal.com/settings/profile", dialog)
        self.assertIn("API Tokens &amp; Service Users", dialog)
        self.assertIn("https://modal.com/pricing", dialog)
        self.assertIn("Succeeded!", dialog)
        self.assertIn("settings/${encodeURIComponent(workspace)}/usage", dialog)
        self.assertIn("Modal's billing page", dialog)
        self.assertIn("Start generating", dialog)
        self.assertNotIn("Repair model files", dialog)
        self.assertNotIn("forceAssets", dialog)

    def test_workflow_models_are_installed_incrementally(self):
        manifest = json.loads((ROOT / "assets" / "models.json").read_text(encoding="utf-8"))
        workflows = manifest["workflows"]
        self.assertEqual(["ultrasharp-4x"], workflows["lite-upscale"])
        self.assertEqual(
            set(workflows["image-edit"]),
            set(workflows["try-on"]) - {"qwen-clothes-try-on"},
        )
        self.assertEqual(
            {"z-image-turbo-bf16", "z-image-qwen3-4b", "z-image-vae"},
            set(workflows["text-to-image"]),
        )
        self.assertEqual(
            {"hunyuan3d-dit-v2-1-fp16", "hunyuan3d-vae-v2-1-fp16", "hunyuan3d-paint-pbr", "dinov2-giant"},
            set(workflows["image-to-3d"]),
        )
        executor = (ROOT / "modal" / "goose_studio_executor.py").read_text(encoding="utf-8")
        self.assertIn('@api.post("/workflows/install")', executor)
        self.assertIn("installed_workflows", executor)
        self.assertIn("_start_download_heartbeat", executor)
        dialog = (ROOT / "web" / "src" / "components" / "WorkflowInstallDialog.tsx").read_text(encoding="utf-8")
        self.assertIn("Technical details", dialog)
        self.assertIn("detailLines.join", dialog)
        self.assertIn('className="setup-details" open', dialog)

    def test_text_to_image_is_the_starter_workflow(self):
        bootstrap = (ROOT / "modal" / "bootstrap.py").read_text(encoding="utf-8")
        self.assertIn('_download_models(manifest, "text-to-image")', bootstrap)
        self.assertIn(' | {"text-to-image"}', bootstrap)
        executor = (ROOT / "modal" / "goose_studio_executor.py").read_text(encoding="utf-8")
        self.assertNotIn('workflow == "lite-upscale"', executor)
        app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("{ id: 'text-to-image' as const", app)
        self.assertIn("useState<WorkflowKind>('text-to-image')", app)
        self.assertIn("{ id: 'lite-upscale' as const", app)

    def test_initial_connection_check_blocks_main_page(self):
        app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "src" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("const [initializing, setInitializing] = useState(true)", app)
        self.assertIn("loadConfig().finally(() => setInitializing(false))", app)
        self.assertIn("if (initializing) return <StartupLoadingScreen />", app)
        self.assertIn(".startup-loading", styles)

    def test_docker_image_contains_all_custom_nodes(self):
        installer = (ROOT / "scripts" / "install.py").read_text(encoding="utf-8")
        self.assertNotIn("prepare-custom-nodes.py", installer)
        nodes = (ROOT / "scripts" / "prepare-custom-nodes.py").read_text(encoding="utf-8")
        self.assertIn('"comfyui-segment-anything-2"', nodes)
        self.assertIn('"ComfyUI-Hunyuan3d-2-1"', nodes)
        self.assertTrue((ROOT / "myhelpers" / "__init__.py").is_file())
        self.assertTrue((ROOT / "myhelpers" / "mesh_geometry.py").is_file())
        self.assertTrue((ROOT / "myhelpers" / "long_edge_repair.py").is_file())
        self.assertTrue((ROOT / "Dockerfile").is_file())
        self.assertFalse((ROOT / "Dockerfile.runtime").exists())
        self.assertFalse((ROOT / "Dockerfile.standalone").exists())
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY image_custom_nodes/ /comfyui/custom_nodes/", dockerfile)
        self.assertIn("COPY tools/voxelize_glb.py /app/voxelize_glb.py", dockerfile)
        self.assertIn("libopengl0", dockerfile)
        self.assertIn("nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04@sha256:", dockerfile)
        self.assertIn("AS hunyuan-builder", dockerfile)
        self.assertIn("COPY --from=hunyuan-builder /native/", dockerfile)
        self.assertIn("/hy3dpaint/custom_rasterizer", dockerfile)
        self.assertIn("python setup.py install", dockerfile)
        self.assertIn("DifferentiableRenderer", dockerfile)
        executor = (ROOT / "modal" / "goose_studio_executor.py").read_text(encoding="utf-8")
        self.assertIn('"ghcr.io/kokkini/goose-studio-runtime', executor)
        self.assertIn("ae9b39249e6fc8db305cfeb13c8013552c58481a35f4584c6b24d95c15f2d085", executor)
        self.assertNotIn("6301fa731b62641bdaf3b23647f97966986542cb366d99aa8259d746a7e7db3d", executor)
        self.assertNotIn('COMFYUI_ROOT / "custom_nodes"', executor)
        self.assertIn("HUNYUAN3D_PAINT_MODEL", executor)
        self.assertIn("HUNYUAN3D_DINO_MODEL", executor)
        self.assertIn("download_hunyuan3d_assets.py", executor)
        self.assertIn("cache_dir=HUNYUAN_CACHE_ROOT", executor)
        self.assertIn('os.environ["HF_HUB_CACHE"]', executor)
        bootstrap = (ROOT / "modal" / "bootstrap.py").read_text(encoding="utf-8")
        self.assertNotIn("custom-nodes.tar.gz", bootstrap)

    def test_image_to_3d_preserves_the_tuned_painted_path(self):
        workflow = json.loads((ROOT / "web" / "workflows" / "image-to-3d.json").read_text(encoding="utf-8"))
        self.assertEqual(workflow["54"]["inputs"]["steps"], 32)
        self.assertEqual(workflow["54"]["inputs"]["guidance_scale"], 6)
        self.assertEqual(workflow["54"]["inputs"]["seed"], 518321210975604)
        self.assertEqual(workflow["9"]["inputs"]["octree_resolution"], 256)
        self.assertEqual(workflow["9"]["inputs"]["num_chunks"], 16000)
        self.assertEqual(workflow["43"]["inputs"]["max_facenum"], 200000)
        self.assertEqual(workflow["44"]["class_type"], "RepairLongEdgeOutliers")
        self.assertEqual(workflow["44"]["inputs"]["trimesh"], ["43", 0])
        self.assertEqual(workflow["44"]["inputs"]["median_multiplier"], 5.0)
        self.assertEqual(workflow["45"]["inputs"]["trimesh"], ["44", 0])
        self.assertEqual(workflow["19"]["inputs"]["view_weights"], "1, 0.5, 1, 0.5, 1, 1")
        self.assertEqual(workflow["20"]["inputs"]["view_size"], 768)
        self.assertEqual(workflow["20"]["inputs"]["texture_size"], 1024)
        self.assertEqual(workflow["20"]["inputs"]["seed"], 629790424419442)
        self.assertEqual(workflow["57"]["inputs"]["pipeline"], ["49", 2])
        self.assertEqual(workflow["57"]["inputs"]["filename_prefix"], "mesh/REPLACE_JOB_ID/hy_mesh")

    def test_voxelization_workflows_use_the_cpu_converter_and_zip_postprocess(self):
        manifest = json.loads((ROOT / "assets" / "models.json").read_text(encoding="utf-8"))
        self.assertEqual([], manifest["workflows"]["voxelize"])
        self.assertTrue((ROOT / "tools" / "voxelize_glb.py").is_file())

        executor = (ROOT / "modal" / "goose_studio_executor.py").read_text(encoding="utf-8")
        self.assertIn('@api.post("/voxelize")', executor)
        self.assertIn("def process_voxel_job", executor)
        self.assertIn("cpu=2", executor)
        self.assertIn('"numpy==2.4.3"', executor)
        self.assertIn('"trimesh==4.12.2"', executor)
        self.assertIn('"pygltflib==1.16.5"', executor)
        self.assertIn('"pillow==12.1.1"', executor)
        self.assertIn("ZIP_DEFLATED", executor)
        self.assertIn('".vox": "application/octet-stream"', executor)
        self.assertIn('".zip": "application/zip"', executor)

        app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
        api = (ROOT / "web" / "src" / "api.ts").read_text(encoding="utf-8")
        self.assertIn("Voxelize 3D model", app)
        self.assertIn("VoxelResolution", app)
        self.assertIn('min="1" max="256"', app)
        self.assertIn("submitVoxelizationJob", api)
        self.assertIn("postprocess", api)
        self.assertIn("type: 'voxelize'", app)
        self.assertIn("isVoxelPackage", app)

    def test_mesh_outputs_are_collected_as_downloadable_models(self):
        executor = (ROOT / "modal" / "goose_studio_executor.py").read_text(encoding="utf-8")
        self.assertIn('( "images", "gifs", "audio", "meshes" )'.replace(" ", ""), executor.replace(" ", ""))
        self.assertIn('".glb": "model/gltf-binary"', executor)
        app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("isModelOutput", app)
        self.assertIn("3D model ready", app)

    def test_text_to_image_requires_no_upload(self):
        app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("run('text-to-image', []", app)
        self.assertIn("summary: 'Create an image from a prompt'", app)
        self.assertIn("Close-up portrait of a beautiful woman, smiling, with sunlight on her face", app)
        self.assertNotIn("Z-Image Turbo", app)
        self.assertIn("if (files.length)", app)
        executor = (ROOT / "modal" / "goose_studio_executor.py").read_text(encoding="utf-8")
        self.assertNotIn("Upload inputs before submitting", executor)

    def test_gpu_routing_separates_image_and_video_workloads(self):
        executor = (ROOT / "modal" / "goose_studio_executor.py").read_text(encoding="utf-8")
        self.assertIn('IMAGE_GPU_TYPE = os.getenv("GOOSE_STUDIO_IMAGE_GPU", "L40S")', executor)
        self.assertIn('VIDEO_GPU_TYPE = os.getenv("GOOSE_STUDIO_VIDEO_GPU", "H100")', executor)
        self.assertIn("gpu=IMAGE_GPU_TYPE", executor)
        self.assertIn("gpu=VIDEO_GPU_TYPE", executor)
        self.assertIn('workload = payload.get("workload", "video")', executor)
        self.assertIn("process_function = process_image_job if workload == \"image\" else process_video_job", executor)
        self.assertIn("call = process_function.spawn", executor)
        api = (ROOT / "web" / "src" / "api.ts").read_text(encoding="utf-8")
        self.assertIn("workload: WorkloadKind", api)
        self.assertIn("output_node_ids: outputNodeIds, workload", api)
        app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("workflow === 'character-swap' ? 'video' : 'image'", app)

    def test_output_credentials_stay_in_authorization_headers(self):
        api = (ROOT / "web" / "src" / "api.ts").read_text(encoding="utf-8")
        self.assertIn("downloadOutput", api)
        self.assertIn("headers: authHeaders(config)", api)
        self.assertNotIn("api_key: config.apiKey", api)
        executor = (ROOT / "modal" / "goose_studio_executor.py").read_text(encoding="utf-8")
        self.assertIn("def download(job_id: str, output_id: str, _: None = Depends(authorize))", executor)
        self.assertNotIn("def download(job_id: str, output_id: str, api_key: str = \"\")", executor)

    def test_creations_can_be_deleted_without_starting_compute(self):
        app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
        api = (ROOT / "web" / "src" / "api.ts").read_text(encoding="utf-8")
        executor = (ROOT / "modal" / "goose_studio_executor.py").read_text(encoding="utf-8")
        self.assertIn("function HistoryCard", app)
        self.assertIn("history-delete", app)
        self.assertIn("deleteJob(config, creation.job_id)", app)
        self.assertIn("export function deleteJob", api)
        self.assertIn('method: \'DELETE\'', api)
        self.assertIn('@api.delete("/jobs/{job_id}")', executor)
        self.assertIn('Cannot delete a running job', executor)
        self.assertIn('shutil.rmtree(IO_ROOT / "input" / job_id', executor)
        self.assertIn('for namespace in (IO_ROOT / "output").glob(f"*/{job_id}")', executor)
        self.assertNotIn("process_image_job.spawn", executor.split('@api.delete("/jobs/{job_id}")', 1)[1].split('@api.get("/status")', 1)[0])
        self.assertIn("const HISTORY_PAGE_SIZE = 12", app)
        self.assertIn("const visibleHistory = history.slice", app)
        self.assertIn("history-pagination", app)

    def test_workflows_keep_independent_jobs_and_polling(self):
        app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("const [runs, setRuns] = useState<ActiveWorkflowRuns>({})", app)
        self.assertIn("const polling = useRef(new Map<string, number>())", app)
        self.assertIn("updateCurrentWorkflowRun(workflow, jobId", app)
        self.assertIn("polling.current.set(jobId", app)
        self.assertIn("onClick={() => setKind(item.id)}", app)
        self.assertNotIn("setJob(null)", app)

    def test_character_swap_preserves_held_object_by_default(self):
        app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("[characterOnly, setCharacterOnly] = useState(true)", app)
        self.assertIn('Keep the object the person is holding', app)

    def test_electron_replaces_setup_bridge_with_typed_ipc(self):
        main = (ROOT / "web" / "electron" / "main.ts").read_text(encoding="utf-8")
        preload = (ROOT / "web" / "electron" / "preload.ts").read_text(encoding="utf-8")
        desktop = (ROOT / "web" / "src" / "desktop.ts").read_text(encoding="utf-8")
        self.assertIn("desktop:start-setup", main)
        self.assertIn("/mnt/c/Windows/explorer.exe", main)
        self.assertIn("url.protocol !== 'https:'", main)
        self.assertIn("contextBridge.exposeInMainWorld('gooseStudio'", preload)
        self.assertIn("window.gooseStudio", desktop)
        self.assertNotIn("console.log(credentials", main)
        self.assertIn("process.resourcesPath", main)
        self.assertIn("app.getPath('userData')", main)
        self.assertIn("safeStorage.encryptString", main)
        self.assertIn("goose-studio-setup.exe", main)
        self.assertIn("../preload/preload.cjs", main)
        self.assertIn("clean.startsWith('[error] ')", main)
        self.assertNotIn("'--force-assets'", main)
        self.assertIn("goose-studio.log", main)
        self.assertIn("desktop:get-app-log", main)
        self.assertIn("desktop:append-app-log", main)
        self.assertIn("getAppLog", preload)
        self.assertIn("appendAppLog", preload)

    def test_setup_failures_are_visible_and_retryable(self):
        installer = (ROOT / "scripts" / "install.py").read_text(encoding="utf-8")
        dialog = (ROOT / "web" / "src" / "components" / "SetupDialog.tsx").read_text(encoding="utf-8")
        setup_types = (ROOT / "web" / "src" / "types.ts").read_text(encoding="utf-8")
        self.assertIn("[error]", installer)
        self.assertIn('stream.reconfigure(encoding="utf-8", errors="replace")', installer)
        self.assertIn("Setup failed", dialog)
        self.assertIn("See Technical details for more information.", dialog)
        self.assertIn('<details className="setup-details" open>', dialog)
        self.assertIn("Try setup again", dialog)
        self.assertIn("setup-success-title", dialog)
        self.assertNotIn("Add payment info on Modal", dialog)
        self.assertIn("Modal's billing page", dialog)
        self.assertIn("void ensureConnection()", dialog)
        self.assertNotIn("if (await onComplete()) onClose()", dialog)
        self.assertIn("error?: string | null", setup_types)

        modal_cli = (ROOT / "scripts" / "modal-cli.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.setdefault("PYTHONUTF8", "1")', modal_cli)
        self.assertIn('stream.reconfigure(encoding="utf-8", errors="replace")', modal_cli)

        bootstrap = (ROOT / "modal" / "bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("[bootstrap] Downloading model", bootstrap)
        self.assertIn("[bootstrap] Finished snapshot", bootstrap)
        sidecar = (ROOT / "scripts" / "build-windows-sidecar.ps1").read_text(encoding="utf-8")
        self.assertIn("download_hunyuan3d_assets.py", sidecar)

        self.assertIn("run_bootstrap_with_progress", installer)
        self.assertIn("Model download still running", installer)
        self.assertIn('"stage":"resources","current":0', installer)
        self.assertIn('"stage":"resources","current":1', installer)
        self.assertIn('"stage":"models","current":1', installer)
        self.assertIn("'workspace': workspace", installer)
        self.assertIn("'environment': environment", installer)
        self.assertIn('ROOT / "tools" / "voxelize_glb.py"', installer)
        self.assertIn('"app\\tools"', sidecar)
        self.assertIn('"tools\\voxelize_glb.py"', sidecar)

    def test_setup_presentation_is_shared_by_browser_and_electron(self):
        app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("<SetupDialog key={setupInstance} open={setupOpen} fullScreen mandatory={!connected}", app)
        self.assertNotIn("fullScreen={!window.gooseStudio}", app)
        self.assertNotIn("mandatory={!window.gooseStudio", app)
        self.assertIn("View job on Modal", app)
        self.assertIn("https://modal.com/apps/${encodeURIComponent(workspace)}/${encodeURIComponent(environment)}", app)
        self.assertIn("|| 'main'", app)
        self.assertIn("className=\"cancel-button modal-job-link\"", app)
        self.assertNotIn("modal.com/apps?api_key", app)

    def test_settings_menu_and_app_log_viewer_are_available(self):
        app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
        settings = (ROOT / "web" / "src" / "components" / "SettingsMenu.tsx").read_text(encoding="utf-8")
        log_dialog = (ROOT / "web" / "src" / "components" / "AppLogDialog.tsx").read_text(encoding="utf-8")
        desktop = (ROOT / "web" / "src" / "desktop.ts").read_text(encoding="utf-8")
        bridge = (ROOT / "scripts" / "serve-web.py").read_text(encoding="utf-8")
        self.assertIn("<SettingsMenu", app)
        self.assertIn("!connected && <button", app)
        self.assertIn("Setup Modal", app)
        self.assertIn("key={setupInstance}", app)
        self.assertIn("View app log", settings)
        self.assertIn("Connect new Modal account", settings)
        self.assertIn("View Modal's usage", settings)
        self.assertIn("getAppLog", desktop)
        self.assertIn("appendAppLog", desktop)
        self.assertIn("app-log-content", log_dialog)
        self.assertIn("scrollTop = logRef.current.scrollHeight", log_dialog)
        self.assertIn('APP_LOG_PATH = ROOT / "logs" / "goose-studio.log"', bridge)
        self.assertIn('self.path == "/app-log"', bridge)

    def test_goose_studio_identity_and_volume_migration(self):
        executor = (ROOT / "modal" / "goose_studio_executor.py").read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "install.py").read_text(encoding="utf-8")
        app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('APP_NAME = "goose-studio"', executor)
        self.assertIn('os.environ.get("GOOSE_STUDIO_API_KEY"', executor)
        self.assertIn('run_modal("volume", "rename", "--yes"', installer)
        self.assertIn("GOOSE_STUDIO_ENDPOINT", installer)
        self.assertIn("Goose Studio", app)
        self.assertIn("gooseStudioJobs", app)

    def test_packaged_setup_keeps_credentials_out_of_resources_and_commands(self):
        installer = (ROOT / "scripts" / "install.py").read_text(encoding="utf-8")
        main = (ROOT / "web" / "electron" / "main.ts").read_text(encoding="utf-8")
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--resource-root"', installer)
        self.assertIn('parser.add_argument("--modal-cli"', installer)
        self.assertIn('"--from-json"', installer)
        self.assertNotIn('f"GOOSE_STUDIO_API_KEY={api_key}"', installer)
        self.assertIn("line.startsWith('[result] ')", main)
        self.assertIn("web/runtime-config.json", dockerignore)

    def test_windows_installer_is_built_from_pinned_sidecars(self):
        package = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
        build = package["build"]
        self.assertEqual("studio.goose.app", build["appId"])
        self.assertEqual(["out/**/*", "package.json"], build["files"])
        self.assertEqual("node_modules/electron/dist", build["electronDist"])
        self.assertEqual("../build/windows-sidecar", build["extraResources"][0]["from"])
        self.assertEqual("nsis", build["win"]["target"][0]["target"])
        self.assertEqual(["x64"], build["win"]["target"][0]["arch"])
        requirements = (ROOT / "requirements-setup.txt").read_text(encoding="utf-8")
        self.assertIn("modal==1.4.3", requirements)
        self.assertIn("pyinstaller==6.16.0", requirements)
        workflow = (ROOT / ".github" / "workflows" / "windows-release.yml").read_text(encoding="utf-8")
        self.assertIn("windows-latest", workflow)
        self.assertIn("build-windows-sidecar.ps1", workflow)
        self.assertIn("pnpm --dir web package:win", workflow)

    def test_docker_image_keeps_package_caches_out_of_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04@sha256:", dockerfile)
        self.assertIn(
            "--mount=type=cache,id=goose-studio-standalone-uv,target=/root/.cache/uv",
            dockerfile,
        )
        self.assertIn("typing_extensions", dockerfile)
        self.assertIn("PIP_NO_CACHE_DIR=1", dockerfile)
        self.assertIn("--quick-test-for-ci --cpu", dockerfile)
        self.assertNotIn("runpod/worker-comfyui", dockerfile)

    def test_electron_and_runtime_versions_are_declared_separately(self):
        package = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
        electron_version = package["version"]
        bootstrap = (ROOT / "modal" / "bootstrap.py").read_text(encoding="utf-8")
        runtime_version = next(
            line.split('"')[1]
            for line in bootstrap.splitlines()
            if line.startswith("RUNTIME_VERSION = ")
        )

        self.assertEqual(electron_version, "1.1.1")
        self.assertEqual(runtime_version, "v1.2.0")
        self.assertIn(runtime_version, (ROOT / "scripts" / "build-runtime-image.sh").read_text(encoding="utf-8"))
        self.assertIn(
            f"ARG RUNTIME_VERSION={runtime_version.removeprefix('v')}",
            (ROOT / "Dockerfile").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
