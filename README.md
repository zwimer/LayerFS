# LayerFS

Imagine a cross-platform FUSE implementation of overlayfs that also has the ability to unmount and remount the overlay with the 'upper' layer state being preserved; furthermore, with allows more alterations in the lower layer to be reflected in the overlay.

## Requirements

JsonFS is `python` 3.8+

### Linux

 `fusepy`, is required.
```bash
pip3 install fusepy
```

Furthermore, the FUSE kernel module for Linux is required. On Ubuntu this can be done via `apt`:
```bash
sudo apt install fuse
```

### OSX

For OSX: `fusepy`, is required.
```bash
pip3 install fusepy
```

Furthermore, the FUSE kernel module for OSX is required.
```
brew cask install osxfuse
```
# Requirements

`fuse`
`python3.8`

# Sub-mounts

Mounting a filesystem within a LayerFS and creating a symlink from the LayerFS to the new filesystem will lead to undefined behavior.
