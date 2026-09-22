FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        build-essential ca-certificates cmake curl file ninja-build patchelf squashfs-tools \
        python3 python3-pip qt6-base-dev qt6-pdf-dev \
        libgl1 libgl-dev libegl-dev libxcb-cursor0 \
        tesseract-ocr tesseract-ocr-eng && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/readDoc-wheels && \
    python3 -m pip download --disable-pip-version-check \
        --dest /opt/readDoc-wheels \
        'numpy<2' \
        'PyMuPDF==1.26.3' \
        'ctranslate2==4.6.0' \
        'transformers==4.46.3' \
        'sentencepiece==0.2.0' \
        'protobuf==5.28.3'

RUN curl --fail --location --retry 3 \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage \
        --output /opt/appimagetool-x86_64.AppImage && \
    chmod 755 /opt/appimagetool-x86_64.AppImage && \
    offset="$(grep -abo hsqs /opt/appimagetool-x86_64.AppImage | tail -1 | cut -d: -f1)" && \
    test -n "$offset" && \
    unsquashfs -q -o "$offset" -d /opt/appimagetool-root \
        /opt/appimagetool-x86_64.AppImage

CMD ["bash", "/src/packaging/linux/build_inside_container.sh"]
