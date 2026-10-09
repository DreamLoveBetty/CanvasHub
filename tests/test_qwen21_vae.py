"""Portable VAE registry/view tests with tiny synthetic weights; no MLX or network."""
import hashlib
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from backend.qwen21.vae_store import VaeStore, inspect_vae, native_shapes, validate_snapshot
from backend.qwen21.vae_runtime import model_view, vae_signature
from backend.routes.qwen21_routes import create_router

SHAPES = {'encoder.conv_in.weight': [2, 3, 3, 4],
          'decoder.conv_out.weight': [4, 3, 3, 2],
          'decoder.norm.gamma': [2]}


def fixture(path, *, native=False, dtype='F32', mutate=None):
    header = {}; cursor = 0
    for key, dims in SHAPES.items():
        dims=list(dims)
        if not native:
            dims = [dims[0], dims[3], dims[1], dims[2]] if len(dims)==4 else [dims[0], 1, 1]
        width={'F32':4,'F16':2,'BF16':2,'F8_E4M3':1}[dtype]
        end = cursor + math.prod(dims)*width
        header[key] = {'dtype':dtype, 'shape':dims, 'data_offsets':[cursor,end]};cursor=end
    if native: header['__metadata__']={'mflux_version':'0.20.0','quantization_level':'8'}
    if mutate: mutate(header)
    raw=json.dumps(header).encode();path.write_bytes(struct.pack('<Q',len(raw))+raw+b'\0'*cursor)
    return path


class VaeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=VaeStore(self.root/'assets')
        self.config=self.store.shared/'vae/config.json';self.config.parent.mkdir(parents=True)
        self.config.write_text('{}')
        pin={'size':2,'blobId':hashlib.sha1(b'blob 2\0{}').hexdigest()}
        for patch in (mock.patch('backend.qwen21.vae_store.native_shapes',return_value=SHAPES),
                      mock.patch('backend.qwen21.vae_store.CONFIG_PIN',pin)):
            patch.start();self.addCleanup(patch.stop)
        self.file=fixture(self.root/'new.safetensors')

    def test_native_export_whole_model_quantization_metadata_does_not_quantize_vae(self):
        file=fixture(self.file,native=True)
        self.assertEqual(inspect_vae(file)['format'],'mflux')

    def test_diffusers_all_float_precisions_have_same_strict_layout(self):
        for dtype in ('F32','BF16','F16'):
            fixture(self.file,dtype=dtype)
            self.assertEqual(inspect_vae(self.file)['format'],'diffusers')

    def test_reject_pretend_native_metadata_and_incorrect_shapes(self):
        fixture(self.file,mutate=lambda h:h.update(__metadata__={'mflux_version':'0.20.0'}))
        with self.assertRaisesRegex(ValueError,'布局'):inspect_vae(self.file)
        fixture(self.file,native=True,mutate=lambda h:h.pop('__metadata__'))
        with self.assertRaisesRegex(ValueError,'布局'):inspect_vae(self.file)
        fixture(self.file,mutate=lambda h:h['decoder.norm.gamma'].update(shape=[1,2,1]))
        with self.assertRaisesRegex(ValueError,'归一化'):inspect_vae(self.file)

    def test_reject_wrong_architecture_packed_fp8_and_truncation(self):
        for mutation in (lambda h:h.pop('decoder.norm.gamma'),
                         lambda h:h['decoder.norm.gamma'].update(dtype='U32'),
                         lambda h:h['decoder.norm.gamma'].update(data_offsets=[0,8])):
            fixture(self.file,mutate=mutation)
            with self.assertRaises(ValueError):inspect_vae(self.file)
        fixture(self.file,dtype='F8_E4M3')
        with self.assertRaises(ValueError):inspect_vae(self.file)
        fixture(self.file);self.file.write_bytes(self.file.read_bytes()[:-1])
        with self.assertRaises(ValueError):inspect_vae(self.file)

    def test_import_copies_without_rewriting_and_does_not_select(self):
        source=self.file.read_bytes();item=self.store.import_file(str(self.file),'Community VAE')
        self.assertEqual(self.store.selected_id(),'builtin')
        resolved=self.store.resolve(item['id']);self.assertNotIn('path',item)
        self.assertEqual((Path(resolved['path'])/'0.safetensors').read_bytes(),source)
        self.assertEqual(self.file.read_bytes(),source)
        self.assertEqual(self.store.import_file(str(self.file))['id'],item['id'])
        self.assertFalse(list(self.store.directory.glob('.import-*')))

    def test_select_snapshot_new_original_and_missing_do_not_silently_fallback(self):
        item=self.store.import_file(str(self.file));self.store.select(item['id'])
        snapshot=self.store.resolve();sig=vae_signature(snapshot)
        self.assertNotEqual(sig,vae_signature(None))
        self.store.select('builtin');self.assertEqual(self.store.resolve()['id'],'builtin')
        self.assertEqual(vae_signature(snapshot),sig)  # queued choice is immutable
        self.store.select(item['id']);(Path(snapshot['path'])/'0.safetensors').unlink()
        with self.assertRaisesRegex(ValueError,'未回退'):self.store.resolve()
        self.assertTrue(self.store.status()['errors'])
        self.store.select('builtin');self.assertEqual(self.store.resolve()['id'],'builtin')

    def test_detect_modified_custom_files_before_warm_reuse(self):
        item=self.store.import_file(str(self.file));snapshot=self.store.resolve(item['id'])
        file=Path(snapshot['path'])/'0.safetensors';file.write_bytes(file.read_bytes()+b'!')
        with self.assertRaisesRegex(ValueError,'已修改'):vae_signature(snapshot)

    def test_checksum_rejects_tampering_even_with_preserved_stat(self):
        import os
        item=self.store.import_file(str(self.file));snapshot=self.store.resolve(item['id'])
        file=Path(snapshot['path'])/'0.safetensors';stat=file.stat()
        data=file.read_bytes();file.write_bytes(data[:-1]+b'!');os.utime(file,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'校验失败'):validate_snapshot(snapshot,checksum=True)

    def test_invalid_selection_and_path_do_not_fallback(self):
        self.store.directory.mkdir(parents=True);self.store.selection_file.write_text('broken')
        with self.assertRaisesRegex(ValueError,'未回退'):self.store.resolve()
        for value in ('../model',None,'', 'a'*63):
            with self.assertRaises(ValueError):self.store.select(value)
        with self.assertRaises(ValueError):self.store.import_file('../../new.safetensors')
        link=self.root/'link.safetensors';link.symlink_to(self.file)
        with self.assertRaises(ValueError):self.store.import_file(str(link))

    def test_original_view_is_exactly_original_path_without_touching_cache(self):
        cache=self.root/'cache'
        for snapshot in (None,{'id':'builtin'}):
            with model_view(self.root/'base',snapshot,cache) as view:self.assertEqual(view,self.root/'base')
        self.assertFalse(cache.exists())

    def test_custom_view_uses_original_other_components_and_cleans_failure(self):
        item=self.store.import_file(str(self.file));snapshot=self.store.resolve(item['id'])
        base=self.root/'model'
        for name in ('transformer','text_encoder','processor','vae'):(base/name).mkdir(parents=True)
        cache=self.root/'views'
        with self.assertRaisesRegex(RuntimeError,'strict load'):
            with model_view(base,snapshot,cache) as view:
                self.assertEqual((view/'vae').resolve(),Path(snapshot['path']))
                for name in ('transformer','text_encoder','processor'):
                    self.assertEqual((view/name).resolve(),(base/name).resolve())
                raise RuntimeError('strict load failed')
        self.assertEqual(list(cache.iterdir()),[])
        self.assertFalse((base/'vae').is_symlink())

    def test_pinned_config_cannot_be_replaced_during_custom_import(self):
        self.config.write_text('{"not":"qwen"}')
        with self.assertRaisesRegex(ValueError,'配置校验'):self.store.import_file(str(self.file))
        self.assertFalse(self.store.directory.exists())

    def test_routes_require_auth_and_validate_json(self):
        service=mock.Mock();router=create_router(service);handler=mock.Mock()
        handler.require_auth.return_value=False
        self.assertTrue(router.dispatch(handler,'POST','/api/qwen21/vae-import'))
        service.import_vae.assert_not_called()
        handler.require_auth.return_value=True;handler.read_json_body.return_value=[]
        router.dispatch(handler,'POST','/api/qwen21/vae-select')
        service.select_vae.assert_not_called();self.assertEqual(handler.send_json.call_args.args[1],400)
        handler.read_json_body.return_value={'vae_id':'builtin'}
        service.select_vae.return_value={'ok':True}
        router.dispatch(handler,'POST','/api/qwen21/vae-select')
        service.select_vae.assert_called_once_with({'vae_id':'builtin'})


class SchemaTests(unittest.TestCase):
    def test_pinned_rgba_vae_architecture(self):
        shapes=native_shapes();self.assertEqual(len(shapes),238)
        self.assertEqual(shapes['encoder.conv_in.weight'],[96,3,3,4])
        self.assertEqual(shapes['decoder.conv_out.weight'],[4,3,3,144])

if __name__=='__main__':unittest.main()
