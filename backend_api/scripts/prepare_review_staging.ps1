param(
    [string]$StagingPath = 'D:\workspace\TravelMate\local_review_moderation\review-overlay.sqlite3',
    [switch]$Apply
)
$ErrorActionPreference='Stop'
$target=[IO.Path]::GetFullPath($StagingPath)
$boundary=[IO.Path]::GetFullPath('D:\workspace')+[IO.Path]::DirectorySeparatorChar
if (-not [IO.Path]::IsPathRooted($StagingPath) -or
    -not $target.StartsWith($boundary,[StringComparison]::OrdinalIgnoreCase) -or
    [IO.Path]::GetExtension($target) -ne '.sqlite3' -or $target.Substring(2).Contains(':')) {
    throw 'Choose a dedicated .sqlite3 file under D:\workspace.'
}
$directory=Split-Path -Parent $target
$ancestor=$directory
while ($ancestor) {
    if (Test-Path -LiteralPath $ancestor) {
        if ((Get-Item -LiteralPath $ancestor).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Review staging must not use a reparse point.'
        }
    }
    $ancestor=Split-Path -Parent $ancestor
}
if (Test-Path -LiteralPath $target) {
    if ((Get-Item -LiteralPath $target).Attributes -band [IO.FileAttributes]::ReparsePoint) {throw 'Staging file must not be a link.'}
}
if (Test-Path -LiteralPath $directory) {
    $allowed=@((Split-Path -Leaf $target),((Split-Path -Leaf $target)+'-journal'),
               ((Split-Path -Leaf $target)+'-wal'),((Split-Path -Leaf $target)+'-shm'))
    if (@(Get-ChildItem -LiteralPath $directory -Force | Where-Object {$_.Name -notin $allowed}).Count) {
        throw 'Use a dedicated directory without unrelated files.'
    }
    if (@(Get-ChildItem -LiteralPath $directory -Force | Where-Object {
        $_.PSIsContainer -or ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)
    }).Count) {throw 'The dedicated staging directory must contain only regular database files.'}
}
if (-not $Apply) {
    [pscustomobject]@{Action='Plan only';Database=$target;Permissions='Current Windows user and SYSTEM only';
        Setting='FYP_REVIEW_STAGING_PATH';EnvironmentChanged=$false;ServiceRestarted=$false}
    return
}
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$owner=[Security.Principal.WindowsIdentity]::GetCurrent().User
$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$acl=[Security.AccessControl.DirectorySecurity]::new()
$acl.SetOwner($owner)
$acl.SetAccessRuleProtection($true,$false)
foreach ($principal in @($owner,$system)) {
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($principal,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
}
Set-Acl -LiteralPath $directory -AclObject $acl
$fileAcl=[Security.AccessControl.FileSecurity]::new()
$fileAcl.SetOwner($owner)
$fileAcl.SetAccessRuleProtection($true,$false)
foreach ($principal in @($owner,$system)) {
    $fileAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($principal,'FullControl','Allow'))
}
Get-ChildItem -LiteralPath $directory -Force | ForEach-Object {Set-Acl -LiteralPath $_.FullName -AclObject $fileAcl}
$backend=Split-Path -Parent $PSScriptRoot
$python=Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {throw 'The existing Backend interpreter was not found.'}
$previous=$env:FYP_REVIEW_STAGING_PATH
try {
    $env:FYP_REVIEW_STAGING_PATH=$target
    Push-Location $backend
    try {& $python -B -c 'from services.review_staging import initialize; initialize()';if($LASTEXITCODE){throw 'Staging initialization failed.'}}
    finally {Pop-Location}
} finally {$env:FYP_REVIEW_STAGING_PATH=$previous}
Set-Acl -LiteralPath $target -AclObject $fileAcl
foreach ($path in @($directory)+@(Get-ChildItem -LiteralPath $directory -Force | ForEach-Object {$_.FullName})) {
    $actual=Get-Acl -LiteralPath $path
    $sids=@($actual.Access | ForEach-Object {$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value})
    if (-not $actual.AreAccessRulesProtected -or $sids.Count -ne 2 -or @($sids | Where-Object {$_ -notin @($owner.Value,$system.Value)}).Count) {
        throw 'Staging permissions did not pass verification.'
    }
}
[pscustomobject]@{Action='Prepared persistent local moderation';Database=$target;PermissionsVerified=$true;
    EnvironmentChanged=$false;ServiceRestarted=$false}
