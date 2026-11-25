# NASA FIRMS key setup

The default integrated workflow uses NASA FIRMS standard-processing active-fire
data in Stage 3. Configure your own MAP_KEY locally before acquisition. The
key is not supplied with the project. Request one through the
[NASA FIRMS MAP_KEY page](https://firms.modaps.eosdis.nasa.gov/api/map_key/).

The instructions below start at the repository root and use
`configs/workflow.json`. If you select another workflow configuration, use
its path in the status command as well. Existing-archive and bundled-input
validation do not require a key or contact NASA; skip key setup for those
input modes.

## Check the Python environment first

Activate the Conda environment and verify the installed checkout:

```bash
conda activate rp_ghana_fire
python tools/qualify_source_checkout.py --origins-only
```

Activation selects an environment; it does not install the Archive package or
switch editable installations to this checkout. If an import is missing or
the origin check identifies another checkout, stop and follow the editable
installation commands in [environment and recovery](ENVIRONMENT_AND_RECOVERY.md).
All four packages must resolve here before running the key check or workflow.
Keep Windows and WSL installations separate and do not rebind an environment
while another checkout is running in it.

## Option 1: hidden prompt in the current terminal

For WSL/Ubuntu, use Bash:

```bash
read -r -s -p "NASA FIRMS MAP_KEY: " FIRMS_MAP_KEY
printf '\n'
export FIRMS_MAP_KEY
```

For Windows PowerShell:

```powershell
$firmsKeySecure = Read-Host "NASA FIRMS MAP_KEY" -AsSecureString
$firmsKeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($firmsKeySecure)
try {
    $env:FIRMS_MAP_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($firmsKeyPointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($firmsKeyPointer)
    $firmsKeySecure.Dispose()
    Remove-Variable firmsKeySecure, firmsKeyPointer
}
```

Paste only the key at the hidden prompt and press Enter. Its literal value
does not enter command history. Run Stage 3 from this same terminal so Python
inherits the variable. A new terminal needs its own setup. Never paste the key
into chat, a command, documentation or a shared configuration file.

## Option 2: external key file

Create a plain-text file outside the repository and staging folders.
Save only the key on one line, using UTF-8 without a byte-order mark. Set the
file path in the producer YAML selected by
`firms_archive.producer_config` in your workflow configuration. The default
producer is `RP1_Project/rp1_firms_archive/configs/rp1.yaml`.

For WSL Python, an example setting is:

```yaml
key_file: /absolute/path/to/external/firms_map_key.txt
```

For Windows Python, use a Windows path instead:

```yaml
key_file: X:/path/to/external/firms_map_key.txt
```

These are absolute-path placeholders, not supplied files or required locations.
Replace the example with the actual external file path. WSL can also read a
Windows file through its `/mnt/c/...` path. Relative `key_file` paths resolve
against the producer YAML directory. Do not pass a Windows path directly to
WSL Python. The YAML contains the path, never the key itself.

A nonblank `FIRMS_MAP_KEY` takes precedence over `key_file`. To use the file
option, clear an existing environment value with `unset FIRMS_MAP_KEY` in Bash
or `Remove-Item Env:FIRMS_MAP_KEY` in PowerShell.

## Check the effective local configuration

For the default build workflow, run this single-line command from the
repository root. It follows the selected producer configuration and uses the
same key resolver as acquisition, so it recognises both options above:

```bash
python -c "import json; from ghana_fire_archive.core import load_config, map_key; workflow=json.load(open('configs/workflow.json', encoding='utf-8')); key=map_key(load_config(workflow['firms_archive']['producer_config'])); print('FIRMS key is configured' if key else 'FIRMS key is missing'); raise SystemExit(0 if key else 1)"
```

This prints a status, never the key. It checks local presence and format only;
it makes no NASA request and creates no output files. A missing key returns a
non-zero exit status. A malformed key stops with `Invalid local MAP_KEY format`.
A file read or configuration error also needs correction before acquisition.

This is not a NASA authentication test. Actual source availability and API
access are checked during acquisition. Root `archive-plan` is an offline
preview; standalone `ghana-fire-archive plan` contacts NASA. After the local
check passes, follow Stage 3 in the [root runbook](../README.md).

## Standalone Archive use

The standalone Archive retains the same environment/file precedence. From its
own project directory, use its selected producer YAML, for example
`configs/archive.yaml`, rather than the root workflow JSON. Its
[README](../RP1_Project/rp1_firms_archive/README.md) includes self-contained
environment, key and command instructions for an independently copied package.
