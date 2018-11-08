Git Tools
=========

This repo contains some potentially useful git commands. To use, simply clone this repo, and add it to your path. Requires python3 to be installed.

Usage:

    `git co my_branch` - replacement and shortcut for "git checkout" which also writes to a yaml file storing the current checkout "ring".
    `git ring` - provides a menu displaying the current ring. choose a number and hit enter, or input "d" followed by a space separated list of numbers to remove those branches from the ring.
    `git ring --clean` - remove all no longer existing branches or commits from the ring.
    `git bn` - check out the next branch in the ring.
    `git bp` - check out the previous branch in the ring.
    `git pop` - pop the current branch out of the ring. Same as git bp and then removing the branch with git ring.

