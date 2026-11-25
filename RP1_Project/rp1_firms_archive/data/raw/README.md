# NASA acquisition cache

This directory receives original NASA FIRMS files, redacted acquisition receipts,
API date-batch evidence and provider declarations. No NASA downloads are bundled
with the source package. Preserve cache receipts alongside their original files.

Configurations may select another `downloads` directory. Shared cache writers are
serialized by the Archive API. Set `FIRMS_MAP_KEY` in the local process environment
or select an external `key_file`; never put credentials in this directory.
