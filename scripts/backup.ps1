param(
    [string]$OutputDirectory = ".\\backups",
    [string]$ComposeFile = "docker-compose.production.yml"
)

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $OutputDirectory $stamp
New-Item -ItemType Directory -Force -Path $target | Out-Null

# The database dump is portable; named-volume archives preserve uploaded files and indexes.
docker compose -f $ComposeFile exec -T postgres pg_dump -U $env:POSTGRES_USER -d multimodal_rag | Out-File -Encoding utf8 (Join-Path $target "postgres.sql")
docker run --rm -v multimodal-rag-core-project_app_data:/data:ro -v "${PWD}/$target:/backup" alpine sh -c "tar czf /backup/app_data.tar.gz -C /data ."
Get-FileHash (Join-Path $target "postgres.sql"), (Join-Path $target "app_data.tar.gz") | Format-Table | Out-File (Join-Path $target "SHA256SUMS.txt")
Write-Host "Backup created at $target"
