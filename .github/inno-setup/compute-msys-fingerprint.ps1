[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$MsysDir,
    [string]$OutputFile = ''
)

$root = (Resolve-Path -LiteralPath $MsysDir).Path.TrimEnd('\', '/')
$files = Get-ChildItem -LiteralPath $MsysDir -Recurse -File -Force |
    Where-Object { $_.Name -ne 'msys-version.txt' } |
    Sort-Object -Property FullName

$sb = [System.Text.StringBuilder]::new()
foreach ($file in $files) {
    $rel = $file.FullName.Substring($root.Length).TrimStart('\', '/')
    $fileHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    [void]$sb.AppendLine($rel + '|' + $fileHash)
}

$sha = [System.Security.Cryptography.SHA256]::Create()
$treeHashBytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($sb.ToString()))
$treeHash = [System.BitConverter]::ToString($treeHashBytes).Replace('-', '').ToLowerInvariant()
$fingerprint = 'msys-' + $treeHash.Substring(0, 16)

if ($OutputFile) {
    [System.IO.File]::WriteAllText(
        $OutputFile,
        $fingerprint + "`r`n",
        [System.Text.UTF8Encoding]::new($false)
    )
}

Write-Output $fingerprint
