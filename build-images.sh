#!/bin/bash

#
# Copyright (C) 2026 tebbi
# SPDX-License-Identifier: GPL-3.0-or-later
#

set -e

images=()
repobase="${REPOBASE:-ghcr.io/tebbiworld}"
reponame="clamav"

# Official ClamAV image (Cisco Talos), pinned. Exposed to the unit as
# ${CLAMAV_IMAGE} through the org.nethserver.images label. The image bundles
# clamd, freshclam and an initial signature database; it is configured through
# CLAMD_CONF_* / FRESHCLAM_CONF_* environment variables (see its entrypoint).
clamav_image="docker.io/clamav/clamav:1.5.4"

# Web/REST front end, built here from web/ and pinned by the module with the
# same tag as the module image (${CLAMAV_WEB_IMAGE}).
webimage="${repobase}/clamav-web:${IMAGETAG:-latest}"
echo "Build the web/REST front end image..."
podman build --force-rm -t "${webimage}" -f web/Containerfile web/
# The CI workflow pushes every image in the list as docker://<image>:${IMAGETAG},
# so list the untagged name and keep an untagged (latest) alias of the build.
podman tag "${webimage}" "${repobase}/clamav-web"
images+=("${repobase}/clamav-web")

runtime_images=(
    "${clamav_image}"
    "${webimage}"
)

container=$(buildah from scratch)

if ! buildah containers --format "{{.ContainerName}}" | grep -q nodebuilder-clamav; then
    echo "Pulling NodeJS runtime..."
    buildah from --name nodebuilder-clamav -v "${PWD}:/usr/src:Z" docker.io/library/node:24.16.0-slim
fi

echo "Build static UI files with node..."
buildah run \
    --workingdir=/usr/src/ui \
    --env="NODE_OPTIONS=--openssl-legacy-provider" \
    nodebuilder-clamav \
    sh -c "yarn install && yarn build"

buildah add "${container}" imageroot /imageroot
buildah add "${container}" ui/dist /ui
# clamd listens on the fixed port 3310 in the host network; node:fwadm lets the
# module open it in the public zone; portsadm lets configure-module allocate
# the front-end port for instances created before 1.1.0. One TCP port for the
# web/REST front end behind Traefik (routeadm).
# One instance per node: clamd listens on the node network, TCP 3310.
buildah config --entrypoint=/ \
    --label="org.nethserver.authorizations=node:fwadm,portsadm traefik@node:routeadm cluster:accountconsumer" \
    --label="org.nethserver.tcp-ports-demand=1" \
    --label="org.nethserver.rootfull=0" \
    --label="org.nethserver.images=${runtime_images[*]}" \
    --label="org.nethserver.max-per-node=1" \
    "${container}"
buildah commit "${container}" "${repobase}/${reponame}"

images+=("${repobase}/${reponame}")

if [[ -n "${CI}" ]]; then
    printf "images=%s\n" "${images[*],,}" >> "${GITHUB_OUTPUT}"
else
    printf "Publish the images with:\n\n"
    printf "  buildah push %s docker://%s\n" "${webimage,,}" "${webimage,,}"
    printf "  buildah push %s docker://%s:%s\n" "${repobase,,}/${reponame,,}" "${repobase,,}/${reponame,,}" "${IMAGETAG:-latest}"
    printf "\n"
fi
