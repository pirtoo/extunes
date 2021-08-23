#!/usr/bin/env python3

# Take a directory of playlist files and upload those playlists to a
# plex server. Music must already be in the plex database (if you've
# just added it wait for the update to finish).
# All changes on the plex side to these playlists are lost.

# Pulls down the list of track in plex and creates a mapping from
# file location to Track objects, likely not the most efficient way
# to do this but it is functional and reasonably fast.

# Uses plex api python module: https://github.com/pkkid/python-plexapi
# pip3 install plexapi
# python3 -m pip install plexapi

import glob
import os.path
import pathlib
import sys

from plexapi.server import PlexServer


# Example global variables.
PLEX_SERVER='http://plex:32400'
PLEX_AUTH='XXXXXXXXXXXXXXXXXXXX'
MUSIC='Music'
PLEX_PREFIX='/volume1/music/itunes/'
PL_DIR='/Users/you/Music/iTunes/playlists'


def playlist_file(filename, tracks):
  items=[]
  i=0
  with open(filename, 'r', encoding='utf-8') as infile:
    for line in infile.readlines():
      if line.startswith('#'):
        continue
      i+=1
      # Chamge the filename/path in the file to how it appears to plex
      line=PLEX_PREFIX + line.rstrip().replace('\\', '/').lstrip('../')
      if line in tracks:
        items.append(tracks[line])
      else:
        print('Not found: %s' % line)
  return (i, items)


def main():
  if not os.path.isdir(PL_DIR) and not os.path.islink(PL_DIR):
    print('Playlist dir "%s" does not exist.' % PL_DIR, file=sys.stderr)
    sys.exit(1)

  print('Connecting to plex server.')
  music=PlexServer(PLEX_SERVER, PLEX_AUTH).library.section(MUSIC)

  print('Calling library update.')
  music.update()

  print('Fetching track and playlist data.')

  tracks={}
  for track in music.search(libtype='track'):
    if len(track.locations) > 0:
      tracks[track.locations[0]]=track

  playlists={}
  for playlist_obj in music.playlists():
    playlists[playlist_obj.title]=playlist_obj

  count=0
  updated=0
  for pl_file in glob.glob(PL_DIR + '/*.m3u'):
    count+=1
    name=pathlib.PurePath(pl_file).stem
    print('Playlist: %s' % name, end='')
    lines, items=playlist_file(pl_file, tracks)
    print(': %s %s ' % (lines, len(items)), end='')

    if name not in playlists:
      print('\n  Creating playlist: %s' % name)
      playlist=music.createPlaylist(title=name, items=items)
    else:
      playlist=playlists[name]
      plex_items=playlist.items()
      print(len(plex_items))
      if items != plex_items:
        # Differences between the local playlist and plex
        updated+=1
        print('  Updating playlist contents from local.')
        playlist.removeItems(plex_items)
        playlist.addItems(items)
        if not set(plex_items).symmetric_difference(set(items)):
          # The API doesn't seem to let you add duplicates in one go
          print('  DUPLICATES, item sets are the same')
          l_count={}
          for item in items:
            if len(locations) > 0:
              l=item.locations[0]
              if l in l_count:
                l_count[l]+=1
              else:
                l_count[l]=1
          for key, value in l_count.items():
            if value > 1:
              print('%s: %s' % (key, value))

  print('\nFinished. %s playlists done, %s updated.' % (count, updated))


if __name__ == '__main__':
  main()
