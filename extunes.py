#!/usr/bin/env python

###########################################################################
# extunes.py v0.06.
# Copyright 2012 by Peter Radcliffe <pir-code@pir.net>.
###########################################################################
# Export iTunes(TM) playlists from the XML file and sync a set of
# playlists and their file contents to a destination under the
# sub-directories 'Music' and 'Playlists'.
#
# Playlist files get re-created every time but doesn't copy music files
# if they already exist and are the same size.
#
# If files or playlists are removed from the synced list then they
# are cleaned up and empty directories are removed.
#
# Requires plistlib which is included with Python 2.6 or later.
# This may work for earlier versions of Python:
#   http://svn.python.org/projects/python/trunk/Lib/plistlib.py
#
# WARNING: will remove anything under the music and playlists
# directories that it isn't syncing on this run!
############################################################################

import argparse
import copy
import os
import urllib
import plistlib
import re
import shutil
import sys
import traceback

FLAGS = None

# Dict entries in playlists and what to flag them as in list mode.
PLAYLIST_FLAGS = (
  ['Master', 'A'],
  ['Music', 'M'],
  ['Visible', 'N'],
  ['Movies', 'V'],
  ['TV Shows', 'T'],
  ['Purchased Music', 'P'],
  ['Party Shuffle', 'D'],
  ['Smart Criteria', 'S'],
)

###########################################################################
# Convert a number of bytes into something human readable.
# Taken from:
# http://goo.gl/zeJZl
def bytes2human(n, format='%(value).4g%(symbol)s'):
  symbols = ('B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y')
  prefix = {}
  for i, s in enumerate(symbols[1:]):
      prefix[s] = 1 << (i+1)*10
  for symbol in reversed(symbols[1:]):
      if n >= prefix[symbol]:
          value = float(n) / prefix[symbol]
          return format % locals()
  return format % dict(symbol=symbols[0], value=n)

###########################################################################
# Convert a track id to a local filename.
def track_name(track, xmlblob):
  try:
    result = name_convert(xmlblob[u'Tracks'][track]['Location'])
  except:
    error_exit('Failed to use iTunes XML data: %s' % trace_last(), code=4)
  return result

###########################################################################
# Convert a track id to a track size in bytes.
def track_size(track, xmlblob):
  try:
    result = xmlblob[u'Tracks'][track]['Size']
  except:
    error_exit('Failed to use iTunes XML data: %s' % trace_last(), code=4)
  return result

###########################################################################
# Get a key from the iTunes xml file with lots of error checking/reporting.
def xml_key(key, xmlblob):
  if key not in xmlblob:
    error_exit('Key missing from iTunes XML data. Corrupt or newer format?',
               code=4)
  try:
    result = xmlblob[key]
  except:
    error_exit('Failed to use iTunes XML data: %s' % trace_last(), code=4)

  return result

###########################################################################
# Convert itunes url style filename to a local filename.
def name_convert(filename):
  return urllib.unquote(filename.split('file://localhost')[1])

###########################################################################
# Convert local filename to a fat32 valid filename relative to playlist.
# This is rather more restictive than it needs to be, which is safer.
#
# If we don't lower case it we can have problems with multi-disk
# albums where the case of the directory is different between iTunes
# sets. Simpler to just lowercase everything, id3 tags will still be
# correct.
# Also get rid of multiple runs of spaces, confuses some systems.
def fat32_convert(filename, oldbase, newbase):
  return re.sub(' +', ' ', re.sub('[^-_/.&%#@a-zA-Z0-9 ]', '',
     os.path.join(newbase, filename.split(oldbase)[1].lower())))

###########################################################################
# Convert UNIX filename to DOS filename.
# The backslash for replacement needs to be overly quoted because
# of the re module.
def dos_convert(filename, relative):
  return re.sub('/', '\\\\', os.path.relpath(filename, relative))

###########################################################################
# Format a list of strings to be quoted and comma seperated.
def quote_list(text_list):
  if not text_list:
    return ''
  return '\'' + '\', \''.join(text_list) + '\''

###########################################################################
# Check if destination directory and it's parents up to stopdir exist.
# Recursive function.
def mkdirsifnotexists(direct, stopdir):
  if direct != stopdir and not os.path.isdir(direct):
    mkdirsifnotexists(os.path.dirname(direct), stopdir)
    #print 'Making directory %s' % direct
    try:
      os.mkdir(direct)
    except (IOError, OSError) as e:
      error_exit('Failed to delete directory "%s":\n  %s\n' %
                 (full_file, e), 6)

###########################################################################
def clean_tree(base, keep_list):

  file_count = 0
  dir_count = 0

  for root, dirs, files in os.walk(base, topdown=False):
    #print root
    #print 'files: %s' % files
    #print 'dirs: %s' % dirs

    # python doesn't copy objects and if we delete from the list we're
    # iterating over it loses its place.
    check_files = copy.copy(files)
    for file in check_files:
      full_file = os.path.join(root, file)

      # if the file isn't in the list, delete it.
      if full_file not in keep_list:
        if not FLAGS.quiet:
          print '  Deleting file "%s"' % full_file
        file_count += 1
        files.remove(file)
        try:
          os.remove(full_file)
        except (IOError, OSError) as e:
          error_exit('Failed to delete file "%s":\n  %s\n' %
                     (full_file, e), 6)

    # Do not remove the base directory.
    if root is base:
      continue

    if len(files) == 0:
      # dirs is generated before we get here so may still have
      # directories in the list that have already been deleted
      # check that they still exist and continue in the for loop
      # if any do.
      empty = True
      for adir in dirs:
        #print 'checking %s' % os.path.join(root, adir)
        if os.path.isdir(os.path.join(root, adir)):
          empty = False
          break

      if not empty:
        continue

      if not FLAGS.quiet:
        print '  Deleting directory "%s"' % root
      dir_count += 1      
      try:
        os.rmdir(root)
      except (IOError, OSError) as e:
        error_exit('Failed to delete directory "%s":\n  %s\n' %
                   (full_file, e), 6)

  return (file_count, dir_count)

###########################################################################
# Print an error to stderr and exit with exit code.
def error_exit(text, code=None):
  sys.stderr.write(sys.argv[0] + ': ' + text)
  if code:
    sys.exit(code)

###########################################################################
# Return the last line of a traceback.
def trace_last():
  return traceback.format_exception(sys.exc_info()[0], sys.exc_info()[1],
                                    sys.exc_info()[2])[-1]

###########################################################################

#for entry in itxml:
#  print entry
#
# Major Version
# Minor Version
# Playlists
# Features
# Library Persistent ID
# Musicpl Folder
# Application Version
# Tracks
# Date


if __name__ == '__main__':
  ## TODO:

  ## check date of itunes lib against a sync file in the destination?

  ## add command line options:
  ##   force sync everything
  ##   paths to be ignored in cleanup under music and playlists
  ##   clean up/remove all files mode.

  ## put all filesystem ops in try blocks
  ## check if dest is under itunes music directory

  ## Count how many deletions would be made on a dry run.
  ## - calculate deletions/additions by number of files in list
  ##   vs. number of files in destination?
  ## - return size of files to be deleted?

  ## Generate a list of local files and a list of to be synced files
  ## and diff, rather than going through the filesystem?

  ## Progress bar optional in quiet mode, # for every 10 files copied.


  # Command line arguments.
  args = argparse.ArgumentParser(description='Export playlists from iTunes.',
                                 fromfile_prefix_chars='@')

  args.add_argument('--itunes', '-i',
                    help='Location of iTunes XML file.',
                    metavar='itunes-xml-file',
                    default='~/Music/iTunes/iTunes Library.xml')
  args.add_argument('--plistdir',
                    help='Name of playlist directory under destination dir.',
                    default='Playlists')
  args.add_argument('--music',
                    help='Name of music directory under destination dir.',
                    default='Music')
  args.add_argument('--quiet', '-q',
                    action='store_true',
                    help='Quiet file copying/deleting output.')
  args.add_argument('--noop', '-n',
                    action='store_true',
                    help='No-op, no operation, dry run.')

  arg_destlist = args.add_mutually_exclusive_group()
  arg_destlist.add_argument('--dest', '-d',
                            help='Destination directory.')
  arg_destlist.add_argument('--list', '-l',
                             action='store_true',
                             help='List laylists found in the XML.')
  
  arg_plists = args.add_mutually_exclusive_group()
  arg_plists.add_argument('--plists', '-p',
                          nargs='+',
                          default=[],
                          help='Playlists to export.')
  arg_plists.add_argument('--all-plists', '-a',
                          action='store_true',
                          default=False,
                          help='Export all playlists.')

  FLAGS = args.parse_args()

  if not FLAGS.list:
    # Arguments that are required if list wasn't given.
    # These are here to error out quickly before the XML is
    # parsed because that takes time.
    if not FLAGS.dest:
      args.error('one of the arguments --dest/-d --list/-l is required')

    if len(FLAGS.plists) == 0 and not FLAGS.all_plists:
      args.error('one of the arguments --plists/-p --all-plists/-a is required')

    if FLAGS.noop:
      print 'noop: No-op mode, no changes will be made!'

    # Detail the other arguments if not dealing with list.
    dest = os.path.expanduser(FLAGS.dest)
    # Error out if the detination doesn't exist.
    if not os.path.isdir(dest):
      error_exit('dest dir not found: "%s"\n' % dest, 5)
    music = os.path.join(dest, FLAGS.music)
    plistdir = os.path.join(dest, FLAGS.plistdir)

    # Make sure playlists and music directories exist.
    print 'Checking paths for existence.'
    for path in [plistdir, music]:
      if not FLAGS.quiet:
        print '  Checking "%s".' % path
      if not os.path.isdir(path):
        if FLAGS.noop and not FLAGS.quiet:
            print '  noop: not creating "%s".' % path
        else:
          if not FLAGS.quiet:
            print '  Creating "%s".' % path

          try:
            os.mkdir(path)
          except (IOError, OSError) as e:
            error_exit('Failed to create directory "%s":\n  %s\n' %
                       (path, e), 6)

  # Try to parse the XML file.
  try:
    itxml = plistlib.readPlist(os.path.expanduser(FLAGS.itunes))
  except IOError as e:
    error_exit('Cannot open "%s": %s' % (FLAGS.itunes, e), 4)
  except:
    error_exit('Failed to parse iTunes XML file "%s":\n  %s' %
               (FLAGS.itunes, trace_last()), code=4)

  dbdate = xml_key('Date', itxml)
  dbver = '%s.%s' % (xml_key('Major Version', itxml),
                     xml_key('Minor Version', itxml))
  musicdir = name_convert(xml_key('Music Folder', itxml))

  print 'XML file version %s, date %s' % (dbver, dbdate)
  print 'Music dir: %s' % musicdir

  found_plists = []
  playlists = []

  # If the list option has been given, list playlists and exit.
  if FLAGS.list:
    print 'Playlists found:'
    for plist in xml_key(u'Playlists', itxml):
      #print plist
      if u'Name' not in plist:
        error_exit('Corrupt playlist data: %s' % plist)
      else:
        # Tag the playlist with flags depending on which keys exist in
        # the playlist entry, smart criteria, all items, etc.
        flags = ''
        for flag in PLAYLIST_FLAGS:
          if flag[0] in plist:
            flags += flag[1]

        name = '\'%s\'' % plist[u'Name']
        size = 0
        if 'Playlist Items' not in plist:
          track_num = 0
        else:
          track_num = len(plist['Playlist Items'])
          for track in plist['Playlist Items']:
            if 'Track ID' not in track:
              error_exit('Corrupt playlist/track data: %s' % track)
              next
            size += track_size(str(track['Track ID']), itxml)
        print ('  {:<38} {:10d} tracks {:>9} {:>8}'.format(
               name, track_num, bytes2human(size), flags))

    all_tracks = xml_key(u'Tracks', itxml)
    total_track_num = len(all_tracks)
    total_size = 0
    for track in all_tracks:
      total_size += all_tracks[track]['Size']
    print ('Total in db: {:12d} tracks {:>9}'.format(total_track_num,
                                               bytes2human(total_size)))
    sys.exit(0)

  print 'Number of tracks in the db: %d' % len(xml_key(u'Tracks', itxml))

  # Go through all the possible playlists and match against the
  # ones we want to copy.
  for plist in xml_key(u'Playlists', itxml):
    # Check the basic playlist contents exist.
    if u'Name' not in plist:
      print 'Corrupt playlist data: %s' % plist
      next

    # If we have a match, copy the lists.
    if FLAGS.all_plists or plist[u'Name'] in FLAGS.plists:
      if not 'Playlist Items' in plist:
        # Empty playlist, ignore it.
        print 'Found empty playlist: %s' % plist[u'Name']
      else:

        # Keep a list of matching playlists we found for display later.
        print 'Found playlist: %s' % plist[u'Name']
        found_plists.append(plist[u'Name'])

        # Make a list of playlists and the tracks in those playlists.
        tracks = []
        for track in plist['Playlist Items']:
          if 'Track ID' not in track:
            error_exit('Corrupt playlist/track data: %s' % track)
            next
          tracks.append(str(track['Track ID']))
        playlists.append([plist['Name'], tracks])

  # Take the list of matching found playlists and remove it from the
  # list of desired playlists to display the missing playlists.
  if FLAGS.all_plists:
    missing_plists = []
  else:
    missing_plists = copy.copy(FLAGS.plists)
    for plist in found_plists:
      missing_plists.remove(plist)

  print 'Playlist(s) to be copied: %s' % quote_list(found_plists)
  print 'Playlist(s) not found: %s' % quote_list(missing_plists)

  # Generate a unique list of all tracks required from all playlists
  # that are to be copied.
  # Also keep track of what playlist files we create.
  tracks = []
  playlist_files = []
  if FLAGS.noop:
    print 'noop: not creating playlists.'
  else:
    print 'Creating playlists.'

  for plist in playlists:
    # Add the tracks from this playlist to the general list, keeping it
    # unique with a set conversion.
    tracks = list(set(tracks + plist[1]))
    # Generate the file name of this playlist.
    plist_name = os.path.join(plistdir, '%s.m3u' % plist[0])
    # Keep a list of playlist filenames.
    playlist_files.append(plist_name)

    # Create playlist file.
    if FLAGS.noop and not FLAGS.quiet:
      print 'noop: not writing to "%s"' % plist_name
    else:
      if not FLAGS.quiet:
        print '  Writing to "%s"' % plist_name
      # Try to write the m3u playlist file out.
      try:
        plist_file = open(plist_name, 'w')
      except (IOError, OSError) as e:
        error_exit('Failed to open new playlist "%s":\n   %s\n' %
                   (path, e), 6)

      for track in plist[1]:
        # As well as filename rewriting these paths need to be relative
        # to the playlists directory and DOS style paths with backslashes
        # rather than slashes.
        plist_track = fat32_convert(track_name(track, itxml), musicdir, music)
        plist_file.write('%s\n' % dos_convert(plist_track, plistdir))
      plist_file.close()
  print 'Number of tracks in desired playlists: %d' % len(tracks)

  synced_size = 0
  for track in tracks:
    # Add up how big the synced size of tracks will be.
    synced_size += track_size(track, itxml)
  print ('Size of synced tracks: %s' % bytes2human(synced_size))

  if FLAGS.noop:
    print 'noop: not cleaning up old playlists.'
  else:  
    (files, dirs) = clean_tree(plistdir, playlist_files)
    print '  Removed %i files and %i directories.' % (files, dirs)

  print 'Checking tracks.'
  synced_tracks = []
  to_sync_tracks = []
  to_sync_size = 0
  for track in tracks:
    local_file = track_name(track, itxml)
    remote_file = fat32_convert(local_file, musicdir, music)
    synced_tracks.append(remote_file)

    # Check if remote file exists already.
    if os.path.isfile(remote_file):
      # If it exists, compare size with os.path.getsize() before copying.
      try:
        local_size = os.path.getsize(local_file)
        remote_size = os.path.getsize(remote_file)
      except (IOError, OSError) as e:
        error_exit('Failed to get filesize: %s\n' % e)
      else:
        if local_size == remote_size:
          # File exists and is the same size, skip it.
          continue

    # If the file doesn't exist or the filesize doesn't match
    # list the file to be copied.
    to_sync_tracks.append((local_file, remote_file))
    to_sync_size += track_size(track, itxml)

  print ('Size of tracks to sync: %s' % bytes2human(to_sync_size))

  # Find tracks that are not on the full list and delete them.
  ## Fix clean_tree so it can run in noop.
  if FLAGS.noop:
    print 'noop: not checking files and directories to remove.'
  else:
    print 'Checking files and directories to remove.'
    (files, dirs) = clean_tree(music, synced_tracks)
    print '  Removed %i file and %i directories.' % (files, dirs)

  # Now that we've freed up whatever disk space can be by deleting things
  # copy any remaining tracks that are needed.
  remaining_tracks = len(to_sync_tracks)
  if remaining_tracks is 0:
    print 'No tracks to copy.'
  else:
    if FLAGS.noop:
      print 'noop: not copying %i remaining tracks.' % remaining_tracks
    else:
      print 'Copying %i remaining tracks.' % remaining_tracks

    for (local_file, remote_file) in to_sync_tracks:
      if FLAGS.noop:
        if not FLAGS.quiet:
          print ('  noop: not copying "%s"\n   to "%s".' %
                 (local_file, remote_file))
      else:
        if not FLAGS.quiet:
          print '  Copying "%s"\n   to "%s".' % (local_file, remote_file)
        # Make the path exist if it doesn't.
        mkdirsifnotexists(os.path.dirname(remote_file), music)
        try:
          ## This copy could be switched to the rsync algorithm?
          shutil.copyfile(local_file, remote_file)
        except (IOError, OSError) as e:
          error_exit('Failed to delete directory "%s":\n  %s\n' %
                     (full_file, e), 6)

