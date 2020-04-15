# Build
Instructions are for a Linux environment supported by Yocto.

To get the build OpenGlow/ForgeFIRM you need to have `repo` installed:

## Install the `repo` utility:

```console
mkdir ~/bin
curl http://commondatastorage.googleapis.com/git-repo-downloads/repo > ~/bin/repo
chmod a+x ~/bin/repo
PATH=${PATH}:~/bin
```
Add the following to the end of ```~/.bashrc``` to permanently add ```repo``` to your path:
```console
export PATH=~/bin:$PATH
```
## Download the BSP source:

```console
mkdir forgefirm
cd forgefirm
repo init -u https://github.com/ScottW514/forgefirm.git -b master -m default.xml
repo sync
```

At the end of the commands you have all meta packages you need to build the basic firmware images.

## Build the OpenGlow/ForgeFIRM image for factory control boards
First time environment setup:
```console
(in forgefirm directory)
MACHINE=glowforge DISTRO=forgefirm . setup-environment build
bitbake forgefirm-image
```
Subsequent builds:
```console
(in forgefirm directory)
. setup-environment build
bitbake forgefirm-image
```

## Bootable Image:
The bootable image can be found in ```forgefirm/build/tmp/deploy/images/```.

It can be written directly to an SDCARD:
```console
(in forgefirm/build directory)
cd tmp/deploy/images/glowforge
sudo zcat forgefirm-image-glowforge.wic.gz | dd of=/dev/sdX bs=1M
```
