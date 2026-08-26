# Release acceptance artifacts

One directory per release, `v<version>/`, holding the `acceptance.json` and
`acceptance.md` that forgetest exported on the bench for that release.
`scripts/release.sh` refuses to sign a release whose artifact does not
authorize the built rootfs; see https://docs.forgefirm.org/developers/acceptance/.
