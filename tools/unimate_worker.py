"""Run UniMate rig preprocessing, sampling, and GLB/Blender export."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Callable


UNIMATE_ROOT = Path("/opt/unimate")
MODEL_ROOT = Path("/assets/models/unimate/unimate_uniml3d_f60_v2")
MODEL_CONFIG = MODEL_ROOT / "config.json"
CHECKPOINT = MODEL_ROOT / "checkpoints" / "checkpoint_step_100000.pt"
OBJECT_TYPE = "unimate_asset"
MAX_MODEL_JOINTS = 60


def save_blender_project(glb_path: Path, blend_path: Path) -> Path:
    """Save a self-contained editing scene without glTF bone display helpers.

    GLB cannot store Blender viewport preferences. Blender's importer may
    create oversized custom bone shapes, so supply a native project too.
    Reimport the final GLB so both downloads contain the same animation.
    """
    import bpy
    from mathutils import Vector

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.render.fps_base = 1.0
    import_options = {"filepath": str(glb_path)}
    # Available in newer Blender importers; the Modal bpy 4.0 importer
    # is supported by removing any custom shapes after import below.
    if "disable_bone_shape" in bpy.ops.import_scene.gltf.get_rna_type().properties:
        import_options["disable_bone_shape"] = True
    bpy.ops.import_scene.gltf(**import_options)

    helpers = set()
    armatures = [obj for obj in scene.objects if obj.type == "ARMATURE"]
    for armature in armatures:
        for bone in armature.pose.bones:
            if bone.custom_shape is not None:
                helpers.add(bone.custom_shape)
            bone.custom_shape = None
        armature.show_in_front = False
        armature.hide_set(True)
    for helper in helpers:
        bpy.data.objects.remove(helper, do_unlink=True)
    for collection in list(bpy.data.collections):
        if collection.name.startswith("glTF_not_exported") and not collection.objects:
            bpy.data.collections.remove(collection)

    meshes = [obj for obj in scene.objects if obj.type == "MESH"]
    if not armatures or not meshes:
        raise RuntimeError("The animated GLB has no rigged mesh for the Blender project.")
    actions = [obj.animation_data.action for obj in armatures
               if obj.animation_data and obj.animation_data.action]
    if not actions:
        raise RuntimeError("The animated GLB has no action for the Blender project.")
    scene.frame_start = int(round(min(action.frame_range[0] for action in actions)))
    scene.frame_end = int(round(max(action.frame_range[1] for action in actions)))
    scene.frame_set(scene.frame_start)
    bpy.context.view_layer.update()

    depsgraph = bpy.context.evaluated_depsgraph_get()
    points = [obj.matrix_world @ Vector(corner)
              for obj in (mesh.evaluated_get(depsgraph) for mesh in meshes)
              for corner in obj.bound_box]
    minimum = Vector([min(point[axis] for point in points) for axis in range(3)])
    maximum = Vector([max(point[axis] for point in points) for axis in range(3)])
    center = (minimum + maximum) / 2
    size = max(maximum - minimum, default=1.0)
    for obj in scene.objects:
        obj.select_set(False)
    for mesh in meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.region_3d.view_location = center
                space.region_3d.view_distance = max(size * 2, 0.1)
                space.region_3d.view_rotation = Vector((1.8, -2.7, 0.8)).to_track_quat('Z', 'Y')
                space.region_3d.view_perspective = 'ORTHO'
                space.shading.type = 'MATERIAL'
                space.clip_end = max(size * 100, 1000)
    for image in bpy.data.images:
        if image.source == "FILE" and image.has_data and not image.packed_file:
            image.pack()
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False, compress=True)
    return blend_path


def _repo_imports() -> None:
    repo = str(UNIMATE_ROOT)
    if repo not in sys.path:
        sys.path.insert(0, repo)


def _merge_animation(asset_path: Path, clip_path: Path, output_path: Path) -> None:
    """Transfer one same-rig clip onto the mesh, checking names and hierarchy."""
    _repo_imports()
    import bpy

    from data_process.mesh_animation.animate_fbx import _action_bone_names, _adopt_action
    from data_process.mesh_animation.common import load_character
    from data_process.utils.blender_rig import (
        export_animated_character,
        get_armature_obj,
        load_file,
        update_scene,
    )

    target = load_character(str(asset_path))
    clip_objects = load_file(str(clip_path))
    source = get_armature_obj(clip_objects)
    if source is None or source.animation_data is None or source.animation_data.action is None:
        raise ValueError("The animation file must contain an armature with an active action.")

    action = source.animation_data.action
    driven = _action_bone_names(action)
    if not driven:
        raise ValueError("The selected animation has no animated bone channels.")

    target_parents = {
        bone.name: bone.parent.name if bone.parent else None
        for bone in target.data.bones
    }
    source_parents = {
        bone.name: bone.parent.name if bone.parent else None
        for bone in source.data.bones
    }
    required = set()
    for name in driven:
        current = name
        while current in source_parents and current not in required:
            required.add(current)
            current = source_parents[current]

    missing = sorted(name for name in required if name not in target_parents)
    mismatched = sorted(
        name for name in required
        if name in target_parents and target_parents[name] != source_parents[name]
    )
    if missing or mismatched:
        details = []
        if missing:
            details.append("missing bones: " + ", ".join(missing[:12]))
        if mismatched:
            details.append("different parent hierarchy: " + ", ".join(mismatched[:12]))
        raise ValueError("The clip is not compatible with the model rig (" + "; ".join(details) + ").")

    _adopt_action(target, action)
    for obj in clip_objects:
        bpy.data.objects.remove(obj, do_unlink=True)

    frame_start, frame_end = action.frame_range
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.frame_start = int(round(frame_start))
    scene.frame_end = int(round(frame_end))
    update_scene()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    export_animated_character(str(output_path.with_suffix("")), formats=("glb",))


def _make_stationary_reference(cond: dict, path: Path) -> None:
    """Create a two-frame rest-pose entry for UniMate's reference-clip loader."""
    import numpy as np

    positions = np.asarray(cond["tpos_first_frame"], dtype=np.float32)
    rotations = np.asarray(cond["tpos_local_rotations"], dtype=np.float32)
    if positions.ndim != 2 or positions.shape[-1] != 3:
        raise ValueError("Preprocessing returned an invalid rest-pose position array.")
    if rotations.shape != (positions.shape[0], 4):
        raise ValueError("Preprocessing returned invalid rest-pose joint rotations.")
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        global_positions=np.repeat(positions[None, ...], 2, axis=0),
        local_rotations=np.repeat(rotations[None, ...], 2, axis=0),
        root_facing_quat=np.tile(np.asarray([1, 0, 0, 0], dtype=np.float32), (2, 1)),
        fps=np.asarray(30, dtype=np.int32),
    )


def _prepare_feature_dataset(preprocessed: Path, feature_root: Path) -> dict:
    import numpy as np

    try:
        condition_map = np.load(preprocessed / "cond.npy", allow_pickle=True).item()
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise RuntimeError("UniMate preprocessing did not produce a valid cond.npy.") from exc
    if not isinstance(condition_map, dict) or len(condition_map) != 1:
        raise RuntimeError("UniMate preprocessing returned an unexpected skeleton condition.")
    cond = next(iter(condition_map.values()))
    joint_count = len(cond.get("parents", []))
    if not 5 <= joint_count <= MAX_MODEL_JOINTS:
        raise ValueError(
            f"This UniMate checkpoint supports 5–{MAX_MODEL_JOINTS} joints; "
            f"the preprocessed rig has {joint_count}."
        )

    motion_dir = feature_root / "motions"
    motion_dir.mkdir(parents=True, exist_ok=True)
    source_motions = sorted((preprocessed / "motions").glob("*.npz"))
    if source_motions:
        for index, source in enumerate(source_motions):
            shutil.copy2(source, motion_dir / f"{OBJECT_TYPE}-clip-{index:03d}.npz")
    else:
        _make_stationary_reference(cond, motion_dir / f"{OBJECT_TYPE}-rest.npz")

    np.save(feature_root / "cond.npy", {OBJECT_TYPE: cond})
    return cond


def _write_inference_config(feature_root: Path, exp_root: Path, prompt: str) -> Path:
    if not MODEL_CONFIG.is_file() or not CHECKPOINT.is_file():
        raise FileNotFoundError("Install the UniMate workflow weights before starting a job.")
    exp_root.mkdir(parents=True, exist_ok=True)
    config = json.loads(MODEL_CONFIG.read_text(encoding="utf-8"))
    config.setdefault("truebones", {})["path"] = str(feature_root)
    config["truebones"]["objects_subset"] = "all"
    config.setdefault("dataset", {})["dataset_list"] = ["truebones"]
    config.setdefault("experiment", {})["output_dir"] = str(exp_root)
    config_path = exp_root / "config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    shutil.copy2(MODEL_ROOT / "dataset_stats.npy", exp_root / "dataset_stats.npy")
    cases_path = exp_root / "test_cases.json"
    cases_path.write_text(
        json.dumps({f"{OBJECT_TYPE}-0": prompt}, ensure_ascii=False),
        encoding="utf-8",
    )
    return cases_path


def run_unimate(
    asset_path: Path,
    clip_path: Path | None,
    prompt: str,
    face_r: str | None,
    face_l: str | None,
    job_root: Path,
    output_path: Path,
    progress: Callable[[str], None],
) -> Path:
    """Preprocess one rig and write one animated GLB to ``output_path``."""
    _repo_imports()
    os.environ["HF_HOME"] = "/assets/huggingface"
    os.environ["HF_HUB_CACHE"] = "/assets/huggingface/hub"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    from data_process.mesh_animation.preprocess_char import preprocess_asset
    from data_process.mesh_animation.animate_motion import animate_character
    from unimate.inference.sample import InferenceArgs, main as sample_motion

    job_root.mkdir(parents=True, exist_ok=True)
    source_path = asset_path
    if clip_path is not None:
        progress("Checking the rig and attaching the reference clip")
        source_path = job_root / "model_with_reference.glb"
        _merge_animation(asset_path, clip_path, source_path)

    progress("Preprocessing the model skeleton")
    preprocessed = job_root / "preprocessed"
    cond = preprocess_asset(
        char_path=str(source_path),
        output_dir=str(preprocessed),
        face_r=face_r or None,
        face_l=face_l or None,
        formats=("glb",),
        save_vis=False,
    )
    if not isinstance(cond, dict):
        raise RuntimeError("UniMate did not return a skeleton condition.")

    feature_root = job_root / "inference_dataset" / "truebones"
    _prepare_feature_dataset(preprocessed, feature_root)
    canonical_asset = preprocessed / f"{source_path.stem}_canonical.glb"
    if not canonical_asset.is_file():
        raise FileNotFoundError("UniMate preprocessing did not produce the canonical GLB.")

    progress("Preparing text and skeleton conditioning")
    exp_root = job_root / "inference_experiment"
    cases_path = _write_inference_config(feature_root, exp_root, prompt)
    sample_dir = job_root / "sampled_motion"

    progress("Generating a 60-frame motion on the Modal GPU")
    sample_motion(
        InferenceArgs(
            exp_dir=str(exp_root),
            model_path=str(CHECKPOINT),
            output_dir=str(sample_dir),
            num_repetitions=1,
            test_cases_json=str(cases_path),
            only_save_motion=True,
            batch_size=1,
        )
    )
    # UniMate writes --only_save_motion outputs under ``output_dir/motions``.
    motion_dir = sample_dir / "motions"
    motion_files = sorted(motion_dir.glob("*.npy"))
    if len(motion_files) != 1:
        raise RuntimeError(
            f"UniMate produced {len(motion_files)} motion files under {motion_dir}; expected one."
        )

    progress("Applying the generated motion and exporting the animated GLB")
    animated_dir = job_root / "animated"
    # The sampler's only_save_motion output is a denormalized (F, J, 12)
    # .npy feature array. animate_motion is UniMate's supported application
    # path for that format; animate_lbs accepts feature .npz files instead.
    # Drive the same source rig used to build cond.npy so the helper can
    # recover rotations and retarget them with the matching T-pose condition.
    animate_character(
        char_path=str(source_path),
        anim_path=str(motion_files[0]),
        cond_path=str(preprocessed / "cond.npy"),
        output_dir=str(animated_dir),
        dataset_type="truebones",
        anim_mode="fk",
        extra_bones_strategy="merge",
    )
    generated = sorted(animated_dir.glob("*.glb"))
    if len(generated) != 1:
        raise RuntimeError("UniMate did not produce one playable animated GLB.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(generated[0], output_path)
    progress("Preparing the Blender project")
    save_blender_project(output_path, output_path.with_suffix(".blend"))
    return output_path
