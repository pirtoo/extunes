# extunes
Python script to export iTunes plist data for playlists and sync music files to other devices.

Apple have migrated from iTunes.app to Music.app.
In Music.app you can export an xml version of the library by going to the "File" menu and choose the "Library" option and using "Export Library..." which lets you save the xml version which should still work here but you will need to manually export it each time.

# plex-playlist-upload
Python script to push a set of playlists up to a plex server.

Can be used to push the results from extunes to plex. It is a one way push, all server side changes to these specific playlists are lost. Media must already exist in the plex database.

Works by pulling down Track objects for every music track in a given music section and indexing them in a dict by file location so the filenames in playlists can be used to identify the objects to check/add/update in the plex playlists. A bit of a hack but reasonably fast. Configured with global variables until I get around to adding command line options.

Outputs the name of each playlist (from the filename, case sensitive since plex is case sensitive about playlist names), the number of files in the playlist file, the number the script successfully identified on the plex server and the number in the playlist on the plex server if it already existed.

Uses py-plexapi from https://github.com/pkkid/python-plexapi