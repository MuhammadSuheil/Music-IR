param([ValidateSet('api','ui','build','preview','test','test-ui','elasticsearch')][string]$Service = 'ui')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($Service -in @('api','test','elasticsearch') -and -not (Test-Path -LiteralPath $taskPython)) {
    throw 'Buat .venv dan install dependensi terlebih dahulu; lihat README.md.'
}
switch ($Service) {
    'elasticsearch' {
        $taskElastic = Join-Path $PSScriptRoot '.cache\elasticsearch\elasticsearch-9.5.6\bin\elasticsearch.bat'
        if (-not (Test-Path -LiteralPath $taskElastic)) { throw 'Jalankan python scripts/setup_elasticsearch.py terlebih dahulu.' }
        $env:ES_TMPDIR = Join-Path $PSScriptRoot '.cache\elasticsearch\tmp'
        New-Item -ItemType Directory -Force -Path $env:ES_TMPDIR | Out-Null
        & $taskElastic
    }
    'api' { & $taskPython -m uvicorn music_ir.api:app --host 127.0.0.1 --port 8000 --reload --reload-dir music_ir }
    'ui' { npm --prefix frontend run dev }
    'build' { npm --prefix frontend run build }
    'preview' { npm --prefix frontend run preview }
    'test-ui' { npm --prefix frontend test }
    'test' { & $taskPython -m unittest discover -s tests -v }
}
exit $LASTEXITCODE
