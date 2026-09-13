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

runtime_images=(
    "${clamav_image}"
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
# No Traefik route and no allocated port: clamd listens on the fixed port 3310
# in the host network. node:fwadm lets the module open that port in the public
# zone when LAN access is enabled.
buildah config --entrypoint=/ \
    --label="org.nethserver.authorizations=node:fwadm" \
    --label="org.nethserver.tcp-ports-demand=0" \
    --label="org.nethserver.rootfull=0" \
    --label="org.nethserver.images=${runtime_images[*]}" \
    "${container}"
buildah commit "${container}" "${repobase}/${reponame}"

images+=("${repobase}/${reponame}")

if [[ -n "${CI}" ]]; then
    printf "images=%s\n" "${images[*],,}" >> "${GITHUB_OUTPUT}"
else
    printf "Publish the images with:\n\n"
    for image in "${images[@],,}"; do printf "  buildah push %s docker://%s:%s\n" "${image}" "${image}" "${IMAGETAG:-latest}" ; done
    printf "\n"
fi
