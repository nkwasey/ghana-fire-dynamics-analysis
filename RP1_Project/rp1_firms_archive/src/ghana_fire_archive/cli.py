from __future__ import annotations
import argparse
import json
from pathlib import Path
from zipfile import BadZipFile
from .core import ArchiveError, verify, write_json
from .api import load_config, make_plan, download, prepare_and_export, validate_archive, writer_lock
from .exports import export_annual, package_collection, verify_annual
from .scientific import write_quality_sidecars
from . import __version__


def main(argv=None):
    p=argparse.ArgumentParser(description='Ghana FIRMS standard-processing annual archive')
    p.add_argument('--version',action='version',version=f'%(prog)s {__version__}')
    p.add_argument('command',choices=['plan','download','prepare','build','verify','qa','export','package'],
                   help='plan/download/prepare/build/verify an archive, create QA flags, export sensor folders, or package annual ZIPs')
    p.add_argument('--config',default=str(Path(__file__).resolve().parents[2]/'configs/archive.yaml'),
                   help='YAML configuration path (default: project configs/archive.yaml)')
    p.add_argument('--year',type=int,help='request one year; retains the configured output directory')
    p.add_argument('--start-year',type=int,help='first requested year, inclusive; requires --end-year')
    p.add_argument('--end-year',type=int,help='last requested year, inclusive; requires --start-year')
    p.add_argument('--run-id',help='run directory name under configured output_root; explicit output configs retain their path')
    p.add_argument('--cached-catalogue',action='store_true',
                   help='reuse saved annual catalogue; API availability and uncached data can still require network access')
    p.add_argument('--manifest',help='accepted input manifest for verify/qa/export/package (default: configured output archive)')
    p.add_argument('--output',help='verify/export directory, QA directory, or package destination ZIP')
    args=p.parse_args(argv)
    if args.year is not None and (args.start_year is not None or args.end_year is not None):p.error('Choose --year or a start/end year range, not both')
    if (args.manifest or args.output) and args.command not in ('verify','qa','export','package'):p.error('--manifest/--output apply only to verify, qa, export and package')
    if args.command in ('qa','export','package') and any(v is not None for v in (args.year,args.start_year,args.end_year)):
        p.error('qa/export/package use the entire accepted manifest; select years when preparing the archive')
    if args.manifest and any(v is not None for v in (args.year,args.start_year,args.end_year,args.run_id)):
        p.error('--manifest selects an accepted archive; year and run options require configuration')
    try:
        if args.manifest:
            manifest=Path(args.manifest).resolve()
            c={'output':str(manifest.parent)}
        else:
            c=load_config(args.config,args.year,args.start_year,args.end_year,run_id=args.run_id)
            manifest=Path(c['output'])/'archive-manifest.json'
        if args.command=='plan':
            result=make_plan(c,not args.cached_catalogue)
            print(json.dumps(result,indent=2))
        elif args.command=='download':
            result=download(c,not args.cached_catalogue)
            print(json.dumps({'downloaded_or_verified':sum(i['status']=='available' for i in result['items']),'unavailable':sum(i['status']=='unavailable' for i in result['items'])}))
        elif args.command=='prepare':
            result,exports=prepare_and_export(c)
            print(json.dumps({'manifest':str(manifest),'records':result['total_records'],'annual_directory':exports['path'],'quality_assurance':exports['quality_assurance'],'complete_available_sp_scope':result['complete_available_sp_scope'],'complete_requested_scope':result['complete_requested_scope']}))
        elif args.command=='build':
            result,exports=prepare_and_export(c,download(c,not args.cached_catalogue))
            print(json.dumps({'manifest':str(manifest),'records':result['total_records'],'annual_directory':exports['path'],'quality_assurance':exports['quality_assurance'],'complete_available_sp_scope':result['complete_available_sp_scope'],'complete_requested_scope':result['complete_requested_scope']}))
        elif args.command=='qa':
            with writer_lock(manifest.parent):
                verify(manifest,write_report=False)
                result=write_quality_sidecars(manifest,args.output or manifest.parent/'qa')
            print(json.dumps(result,indent=2))
        elif args.command=='export':
            with writer_lock(manifest.parent,args.output or manifest.parent):
                result=export_annual(manifest,args.output or manifest.parent)
            print(json.dumps(result,indent=2))
        elif args.command=='package':
            destination=Path(args.output or manifest.parent/'Ghana_Fire_Archive_Annual_Shapefiles.zip')
            with writer_lock(manifest.parent,destination.resolve().parent):
                result=package_collection(manifest,destination)
            print(json.dumps(result,indent=2))
        else:
            result=validate_archive(manifest)
            if args.output:
                destination=Path(args.output).resolve()
                if destination.is_relative_to(manifest.parent):
                    raise ArchiveError('Choose a separate --output directory for the verification report')
                write_json(destination/'verification.json',result)
            print(json.dumps(result,indent=2))
    except (ArchiveError, OSError, ValueError, BadZipFile) as e:
        p.exit(1,f'Archive operation stopped: {e}\n')


if __name__=='__main__': main()
