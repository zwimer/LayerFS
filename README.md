# LayerFS

Imagine a cross-platform FUSE implementation of overlayfs that also has the ability to unmount and remount he overlay with the 'upper' layer state being preserved; furthermore, with allows more alterations in the lower layer to be reflected in the overlay.

# Requirements

`fuse`
`python3.8`

# Sub-mounts

Mounting a filesystem within a LayerFS and creating a symlink from the LayerFS to the new filesystem will lead to undefined behavior.
