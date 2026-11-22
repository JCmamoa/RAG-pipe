<#
 End-to-end smoke test (PowerShell 5.1+ / Windows 10): registers an organization, uploads a PDF straight to
 MinIO, waits for ingestion and runs a semantic search.

 Usage:  .\scripts\smoke.ps1 -Pdf .\my-document.pdf -Question "What is this document about?"
 Needs:  the stack running (docker compose --profile local-llm up) with the models already pulled.
#>
param(
  [Parameter(Mandatory = $true)][string]$Pdf,
  [string]$Question = "What is the main subject of the document?",
  [string]$BaseUrl = "http://localhost:8000"
)
$ErrorActionPreference = "Stop"
$Pdf = (Resolve-Path $Pdf).Path

$email = "smoke-$([guid]::NewGuid().ToString('N').Substring(0,8))@demo.test"
$reg = Invoke-RestMethod -Method Post -Uri "$BaseUrl/auth/register" -ContentType "application/json" `
  -Body (@{ org_name = "Smoke Org"; email = $email; password = "strong-password-123" } | ConvertTo-Json)
$h = @{ Authorization = "Bearer $($reg.access_token)" }
Write-Host "Organization created, user $email"

$size = (Get-Item $Pdf).Length
$ticket = Invoke-RestMethod -Method Post -Uri "$BaseUrl/documents" -Headers $h -ContentType "application/json" `
  -Body (@{ filename = (Split-Path $Pdf -Leaf); size_bytes = $size } | ConvertTo-Json)
$docId = $ticket.document.id
Write-Host "Document $docId (pending). Uploading to MinIO..."

# Multipart POST straight to MinIO. curl.exe ships with Windows 10; the file must be the LAST form field.
$curlArgs = @("-s", "-S", "-f", "-o", "NUL")
foreach ($p in $ticket.upload.fields.PSObject.Properties) { $curlArgs += @("-F", "$($p.Name)=$($p.Value)") }
$curlArgs += @("-F", "file=@$Pdf", $ticket.upload.url)
& curl.exe @curlArgs
if ($LASTEXITCODE -ne 0) { throw "Upload to MinIO failed (curl exit $LASTEXITCODE)" }

Write-Host "Waiting for ingestion (webhook -> Celery -> embeddings)..."
$deadline = (Get-Date).AddMinutes(10)
do {
  Start-Sleep -Seconds 3
  $doc = Invoke-RestMethod -Uri "$BaseUrl/documents/$docId" -Headers $h
  Write-Host "  status: $($doc.status)"
  if ($doc.status -eq "pending") {
    # Fallback if the MinIO event has not arrived yet: confirm manually (idempotent).
    try { Invoke-RestMethod -Method Post -Uri "$BaseUrl/documents/$docId/confirm" -Headers $h | Out-Null } catch {}
  }
} while ($doc.status -notin @("ready", "failed") -and (Get-Date) -lt $deadline)

if ($doc.status -ne "ready") { throw "Ingestion ended as '$($doc.status)': $($doc.error)" }
Write-Host "Ready: $($doc.page_count) pages."

$hits = Invoke-RestMethod -Method Post -Uri "$BaseUrl/search" -Headers $h -ContentType "application/json" `
  -Body (@{ query = $Question; k = 3 } | ConvertTo-Json)
foreach ($hit in $hits) {
  $snippet = $hit.content.Substring(0, [Math]::Min(160, $hit.content.Length)).Replace("`n", " ")
  Write-Host ("[{0:N3}] {1} p.{2}: {3}..." -f $hit.score, $hit.filename, $hit.page, $snippet)
}
Write-Host "`nOpen $BaseUrl/ui/ to chat with the document."
