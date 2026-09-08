# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.10.12 AS uv

# Build Hunyuan3D's Linux native extensions separately. The final image uses
# the CUDA runtime base, while only the compiled Python extensions are copied
# into it.
FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04@sha256:24c8e3581ea6330038b0d374920721983312627f8adbfcf390bdb4b399d280ed AS hunyuan-builder

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_NO_INPUT=1 \
    PYTHONUNBUFFERED=1 \
    UV_HTTP_RETRIES=5 \
    UV_HTTP_TIMEOUT=300 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:/usr/local/cuda/bin:${PATH}" \
    TORCH_CUDA_ARCH_LIST="8.6;8.9;9.0"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        python3.12 \
        python3.12-dev \
        python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

RUN uv venv --python /usr/bin/python3.12 /opt/venv \
    && uv pip install \
        torch==2.10.0 \
        --index-url https://download.pytorch.org/whl/cu128 \
    && uv pip install pybind11==3.1.0 ninja

COPY image_custom_nodes/ComfyUI-Hunyuan3d-2-1 /src/ComfyUI-Hunyuan3d-2-1

RUN cd /src/ComfyUI-Hunyuan3d-2-1/hy3dpaint/custom_rasterizer \
    && python setup.py install \
    && cd ../DifferentiableRenderer \
    && python setup.py install \
    && mkdir -p /native/custom_rasterizer \
    && cp -a /opt/venv/lib/python3.12/site-packages/custom_rasterizer-*.egg/custom_rasterizer/. /native/custom_rasterizer/ \
    && cp -a /opt/venv/lib/python3.12/site-packages/custom_rasterizer-*.egg/custom_rasterizer_kernel* /native/ \
    && cp -a /opt/venv/lib/python3.12/site-packages/mesh_inpaint_processor-*.egg/mesh_inpaint_processor* /native/

FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04@sha256:ac55d124da4882b497f732d8dfd9a702d5447a5f29d08d56da6f64f0a1eb34bc

ARG RUNTIME_VERSION=1.3.0
ARG COMFYUI_REF=ace9172e95038ac25015c419713aa7755f739034
LABEL org.opencontainers.image.title="Goose Studio ComfyUI Runtime"
LABEL org.opencontainers.image.version="${RUNTIME_VERSION}"
LABEL org.opencontainers.image.source="https://github.com/kokkini/goose-studio"

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_NO_INPUT=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_HTTP_RETRIES=5 \
    UV_HTTP_TIMEOUT=300 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        ffmpeg \
        git \
        libgl1 \
        libglib2.0-0 \
        libopengl0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        python3.12 \
        python3.12-dev \
        python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

RUN uv venv --python /usr/bin/python3.12 /opt/venv \
    && git init /comfyui \
    && git -C /comfyui fetch --depth 1 https://github.com/Comfy-Org/ComfyUI.git "${COMFYUI_REF}" \
    && git -C /comfyui checkout --detach FETCH_HEAD

COPY requirements-runtime.txt /tmp/requirements-runtime.txt

RUN --mount=type=cache,id=goose-studio-standalone-uv,target=/root/.cache/uv \
    uv pip install \
        torch==2.10.0 \
        torchvision==0.25.0 \
        torchaudio==2.10.0 \
        --index-url https://download.pytorch.org/whl/cu128 \
    && uv pip install \
        --requirements /comfyui/requirements.txt \
        --requirements /tmp/requirements-runtime.txt \
    && uv pip install --upgrade --no-deps protobuf==7.35.1 \
    && rm -rf /comfyui/.git /tmp/requirements-runtime.txt /root/.cache/pip

COPY image_custom_nodes/ /comfyui/custom_nodes/
COPY tools/voxelize_glb.py /app/voxelize_glb.py

WORKDIR /comfyui

RUN timeout 300 python main.py --quick-test-for-ci --cpu \
    && rm -rf /comfyui/temp /comfyui/user /root/.cache

# Hunyuan3D's textured workflow uses two native extensions compiled against
# the same CUDA 12.8/PyTorch stack in the builder stage.
COPY --from=hunyuan-builder /native/ /opt/venv/lib/python3.12/site-packages/

# Fail the image build if the exported Python environment is incomplete or
# corrupted. This is intentionally after the final cleanup layer so the check
# covers the exact environment that will be shipped.
RUN python -c "import torch, typing_extensions; assert torch.__version__ == '2.10.0+cu128', torch.__version__; assert hasattr(typing_extensions, 'ParamSpec'); print('Validated torch', torch.__version__, 'and typing_extensions')" \
    && test -n "$(find /opt/venv/lib/python3.12/site-packages -maxdepth 1 -name 'custom_rasterizer_kernel*.so' -print -quit)" \
    && test -n "$(find /opt/venv/lib/python3.12/site-packages -maxdepth 1 -name 'mesh_inpaint_processor*.so' -print -quit)"

ENTRYPOINT []
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188"]
