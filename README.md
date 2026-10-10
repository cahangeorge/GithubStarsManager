# Official Stars updates

Application source: [main](https://github.com/cahangeorge/GithubStarsManager/tree/main), an exact copy of `AmintaCCCP/GithubStarsManager:main`.
This `automation` branch is the default only so GitHub can schedule the updater without adding custom files to the application.

Every hour, the workflow synchronizes `main`, builds the official `Dockerfile.fullstack` for amd64/arm64, and updates the existing Coolify service at stars.omnestack.com. Manual dispatch also retries an interrupted build/deployment. Existing SHA-tagged images are reused; unchanged deployments do not restart.

Application code is checked out at the exact upstream SHA. A JSON build identity file is added to the image's static assets; application source and behavior remain official. The deploy job checks out only this branch and receives Coolify secrets. No old custom application code is used. Image package: `ghcr.io/cahangeorge/github-stars-manager-official-fullstack`, owned by this fork. The existing service, domain, environment, and data volume are retained. Only the image scalar in the saved Compose is changed.

## Acceptance and verification

1. Fork `main` SHA equals upstream `main` SHA.
2. Actual workflow builds/publishes the official image and passes an API health smoke test.
3. Coolify's fixed component is configured for that image digest, the public build identity matches the official SHA, public health passes, and Compose semantics apart from the image are unchanged.
4. A second run reuses the SHA image and performs no deployment mutation.

Commands: `python3 -m unittest discover -s scripts -p 'test_*.py' -v`; manual run: `gh workflow run official-update.yml -R cahangeorge/GithubStarsManager --ref automation`.

Deployment activates only after environment `stars-production` contains `COOLIFY_API_URL` and `COOLIFY_TOKEN` and repository variable `OFFICIAL_AUTO_DEPLOY` is `true`. Until then, synchronization/build can be verified with manual input `deploy=false` and deployment remains disabled.

Initial package creation uses manual input `first_build=true`; subsequent runs must use its default `false` to preserve reuse of immutable SHA-tagged images.

Boundaries: preserve volumes, environment, API/encryption keys and unrelated local work; no application customizations, database reset, automatic rollback, or secret values in logs. Failures stop deployment and remain visible in GitHub Actions. GitHub schedules may be delayed or disabled after 60 days without repository activity; the sync job periodically refreshes this automation branch's activity to keep scheduling enabled.
