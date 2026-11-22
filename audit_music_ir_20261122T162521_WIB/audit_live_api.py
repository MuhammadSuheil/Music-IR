"""Audit-only read-only runtime observation endpoint; original app/search unchanged."""
import sys
from audit_collect import ROOT
sys.path.insert(0,str(ROOT))
from music_ir.api import app

@app.get('/_audit/runtime')
def observe_runtime():
    import torch
    e=app.state.engine
    m=e.semantic.model
    return {'backend_class':type(e.lexical).__name__,'backend':e.backend,'effective_config':e.config,
            'semantic_ready':e.semantic.ready,'encoder_loaded':m is not None,
            'device':str(m.device) if m is not None else None,'dtype':str(next(m.parameters()).dtype) if m is not None else None,
            'max_seq_length':m.max_seq_length if m is not None else None,
            'embedding_dimension':m.get_embedding_dimension() if m is not None else None,
            'torch_threads':torch.get_num_threads(),'cuda_available':torch.cuda.is_available(),
            'document_vector_shape':list(e.semantic.vectors.shape) if e.semantic.vectors is not None else None,
            'document_vector_dtype':str(e.semantic.vectors.dtype) if e.semantic.vectors is not None else None}

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8000)
