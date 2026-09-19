[CmdletBinding()]
param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet('init','start','stop','doctor','backup','restore','upgrade','rollback')]
    [string]$Action,
    [ValidateSet('production','demo','integration')]
    [string]$Profile = 'production',
    [string]$Archive,
    [string]$ReleaseImage,
    [string]$RouteImage,
    [string]$ReleaseManifest,
    [string]$DeliveryIndex,
    [string]$ComposeFile = 'compose.yaml'
)
$ErrorActionPreference = 'Stop'

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$ProfileBase = Join-Path $env:LOCALAPPDATA 'LexAegis'
$DataRoot = Join-Path $ProfileBase $Profile
$AppData = Join-Path $DataRoot 'app'
$GatewayData = Join-Path $DataRoot 'gateway'
$ProfileManifest = Join-Path $AppData 'release-build-manifest.json'
$EnvFile = Join-Path $DataRoot 'runtime.env'
$Project = "lexaegis-$Profile"
$ApiPort = @{ production=38765; demo=48765; integration=58765 }[$Profile]
$RequestedReleaseImage = $ReleaseImage
$RequestedRouteImage = $RouteImage
$RequestedReleaseManifest = $ReleaseManifest
if (-not $ReleaseManifest) { $ReleaseManifest = Join-Path $Repo 'release-build-manifest.json' }
$ComposeFiles = @('-f', (Join-Path $Repo $ComposeFile))
if ($Profile -eq 'demo') { $ComposeFiles = @('-f', (Join-Path $Repo 'compose.demo.yaml')) }
if ($Profile -eq 'integration') { $ComposeFiles += @('-f', (Join-Path $Repo 'compose.integration.yaml')) }
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Write-Utf8Lines([string]$Path, [string[]]$Lines) {
    [System.IO.File]::WriteAllLines($Path, $Lines, $Utf8NoBom)
}

function Write-EnvFile {
    New-Item -ItemType Directory -Force -Path $AppData,$GatewayData | Out-Null
    $previousProfile = $env:LEX_RUN_PROFILE
    $env:LEX_RUN_PROFILE = $Profile
    try {
        $bind = 'from lexaegis.runtime_profile import bind_runtime; import sys; bind_runtime(sys.argv[1], "app", sys.argv[3]); bind_runtime(sys.argv[2], "gateway", sys.argv[3])'
        Invoke-PinnedPython -Image (Get-SelectedImage) -Volumes @("$($AppData):/data", "$($GatewayData):/gateway") -Environment @("LEX_RUN_PROFILE=$Profile") -PythonArguments @('-c', $bind, '/data', '/gateway', $Profile)
    } finally {
        $env:LEX_RUN_PROFILE = $previousProfile
    }
    if (-not (Test-Path $ProfileManifest) -and (Test-Path $ReleaseManifest -PathType Leaf)) {
        Copy-Item -LiteralPath $ReleaseManifest -Destination $ProfileManifest
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $DataRoot /inheritance:r /grant:r "${identity}:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to restrict profile data directory ACL.' }
    if (-not (Test-Path $EnvFile)) {
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        $localBytes = New-Object byte[] 32
        $gatewayBytes = New-Object byte[] 48
        $redteamBytes = New-Object byte[] 48
        $rng.GetBytes($localBytes)
        $rng.GetBytes($gatewayBytes)
        $rng.GetBytes($redteamBytes)
        $rng.Dispose()
        $localPassword = [Convert]::ToBase64String($localBytes)
        $gatewaySecret = [Convert]::ToBase64String($gatewayBytes)
        $redteamSecret = [Convert]::ToBase64String($redteamBytes)
        if (-not $ReleaseImage) { $ReleaseImage = 'lexaegis:local' }
        if (-not $RouteImage) { throw 'Specify the exact locally loaded -RouteImage from the delivery bundle.' }
        $lines = @(
            "LEX_RUN_PROFILE=$Profile",
            "LEX_RELEASE_IMAGE=$ReleaseImage",
            "LEX_PROFILE_ROOT=$($ProfileBase -replace '\\','/')",
            "LEX_COMPOSE_PROJECT=$Project",
            "LEX_COMPOSE_API_PORT=$ApiPort",
            "LEX_APP_DATA_PATH=$($AppData -replace '\\','/')",
            "LEX_GATEWAY_DATA_PATH=$($GatewayData -replace '\\','/')",
            "LEX_RELEASE_BUILD_MANIFEST_HOST_PATH=$($ProfileManifest -replace '\\','/')",
            "LEX_ROUTE_IMAGE=$RouteImage",
            "LEX_LOCAL_PASSWORD=$localPassword",
            "LEX_GATEWAY_SECRET=$gatewaySecret",
            "LEX_REDTEAM_SECRET=$redteamSecret"
        )
        Write-Utf8Lines -Path $EnvFile -Lines $lines
        & icacls.exe $EnvFile /inheritance:r /grant:r "${identity}:F" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Unable to restrict profile environment file ACL.' }
    } else {
        $lines = Get-Content -Path $EnvFile
        $savedProfile = ($lines | Where-Object { $_ -like 'LEX_RUN_PROFILE=*' } | Select-Object -First 1) -replace '^LEX_RUN_PROFILE=', ''
        if ($savedProfile -ne $Profile) { throw 'Profile directory already belongs to a different runtime profile.' }
        if ($ReleaseImage) {
            $lines = @($lines | Where-Object { $_ -notlike 'LEX_RELEASE_IMAGE=*' })
            $lines += "LEX_RELEASE_IMAGE=$ReleaseImage"
            Write-Utf8Lines -Path $EnvFile -Lines $lines
            & icacls.exe $EnvFile /inheritance:r /grant:r "${identity}:F" | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Unable to restrict updated profile environment file ACL.' }
        }
        if ($RouteImage) {
            $lines = @($lines | Where-Object { $_ -notlike 'LEX_ROUTE_IMAGE=*' })
            $lines += "LEX_ROUTE_IMAGE=$RouteImage"
        }
        $lines = @($lines | Where-Object { $_ -notlike 'LEX_RELEASE_BUILD_MANIFEST_HOST_PATH=*' })
        $lines += "LEX_RELEASE_BUILD_MANIFEST_HOST_PATH=$($ProfileManifest -replace '\\','/')"
        Write-Utf8Lines -Path $EnvFile -Lines $lines
        & icacls.exe $EnvFile /inheritance:r /grant:r "${identity}:F" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Unable to restrict updated profile environment file ACL.' }
    }
}

function Get-ConfiguredValue([string]$Name) {
    if (-not (Test-Path $EnvFile)) { return $null }
    $line = Get-Content -Path $EnvFile | Where-Object { $_ -like "$Name=*" } | Select-Object -First 1
    if ($line) { return $line.Substring($Name.Length + 1) }
    return $null
}

function Get-SelectedImage {
    $image = $ReleaseImage
    if (-not $image) { $image = Get-ConfiguredValue 'LEX_RELEASE_IMAGE' }
    if (-not $image) { $image = 'lexaegis:local' }
    & docker image inspect $image | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'The selected fixed runtime image is not present locally; load the reviewed delivery archive first.' }
    return $image
}

function Get-ImageId([string]$Image) {
    $id = & docker image inspect --format '{{.Id}}' $Image
    if ($LASTEXITCODE -ne 0 -or -not $id) { throw "Selected image is not present locally: $Image" }
    return ([string]$id).Trim()
}

function Get-DeliveryValue([string]$Key) {
    if (-not $DeliveryIndex -or -not (Test-Path -Path $DeliveryIndex -PathType Leaf)) {
        throw 'Specify -DeliveryIndex pointing to the extracted delivery.json from the reviewed offline bundle.'
    }
    $delivery = Get-Content -Raw -Path $DeliveryIndex | ConvertFrom-Json
    if ($delivery.schema_version -ne 1) { throw 'Unsupported delivery.json schema.' }
    return [string]$delivery.$Key
}

function Assert-ImageMatchesDelivery([string]$Image, [string]$Key) {
    $expected = Get-DeliveryValue $Key
    if (-not $expected -or (Get-ImageId $Image) -ne $expected) {
        throw "Image $Image does not match $Key in delivery.json."
    }
}

function Invoke-PinnedPython([string]$Image, [string[]]$Volumes, [string[]]$Environment, [string[]]$PythonArguments) {
    $dockerArgs = @('run','--rm','--network','none')
    foreach ($volume in $Volumes) { $dockerArgs += @('-v', $volume) }
    foreach ($variable in $Environment) { $dockerArgs += @('-e', $variable) }
    $dockerArgs += @('--entrypoint','python', $Image)
    $dockerArgs += $PythonArguments
    & docker @dockerArgs
    if ($LASTEXITCODE -ne 0) { throw "Pinned offline maintenance process failed with exit code $LASTEXITCODE" }
}

function Invoke-Maintenance([string[]]$Arguments, [string]$Image) {
    if (-not $Image) { $Image = Get-SelectedImage }
    $hostArchive = if ([IO.Path]::IsPathRooted($Arguments[1])) { $Arguments[1] } else { Join-Path $Repo $Arguments[1] }
    $archiveDirectory = Split-Path -Parent $hostArchive
    $archiveName = Split-Path -Leaf $hostArchive
    if ($archiveDirectory) { New-Item -ItemType Directory -Force -Path $archiveDirectory | Out-Null }
    $containerArchive = "/backup/$archiveName"
    $command = @($Arguments)
    $volumes = @("$($AppData):/data", "$($GatewayData):/gateway", "$($archiveDirectory):/backup")
    if ($command[0] -eq 'backup') {
        if (Test-Path $hostArchive) { throw 'Refusing to overwrite an existing backup archive.' }
        $command[1] = $containerArchive
    } elseif ($command[0] -eq 'restore') {
        if (-not (Test-Path -Path $hostArchive -PathType Leaf)) { throw 'Restore archive does not exist.' }
        $volumes[2] = "$($archiveDirectory):/backup:ro"
        $command = @('restore', $containerArchive, '--target', '/data', '--gateway-target', '/gateway', '--profile', $Profile)
    } else {
        throw 'Unsupported offline maintenance command.'
    }
    $environment = @(
        "LEX_RUN_PROFILE=$Profile", 'LEX_DATA_DIR=/data', 'LEX_GATEWAY_DIR=/gateway',
        'LEX_RELEASE_BUILD_MANIFEST_PATH=/data/release-build-manifest.json',
        "LEX_RELEASE_IMAGE=$Image", "LEX_ROUTE_IMAGE=$(Get-ConfiguredValue 'LEX_ROUTE_IMAGE')"
    )
    Invoke-PinnedPython -Image $Image -Volumes $volumes -Environment $environment -PythonArguments (@('-m','lexaegis.cli') + $command)
}

function Set-ConfiguredValue([string]$Name, [string]$Value) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $lines = @(Get-Content -Path $EnvFile | Where-Object { $_ -notlike "$Name=*" })
    $lines += "$Name=$Value"
    Write-Utf8Lines -Path $EnvFile -Lines $lines
    & icacls.exe $EnvFile /inheritance:r /grant:r "${identity}:F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to restrict updated profile environment file ACL.' }
}

function Get-BackupValue([string]$Path, [string]$Key) {
    if (-not [IO.Path]::IsPathRooted($Path)) { $Path = Join-Path $Repo $Path }
    $image = Get-SelectedImage
    $archiveDirectory = Split-Path -Parent $Path
    $archiveName = Split-Path -Leaf $Path
    $probe = 'import json,sys,zipfile; print(json.loads(zipfile.ZipFile(sys.argv[1]).read("manifest.json")).get(sys.argv[2]) or "")'
    $value = Invoke-PinnedPython -Image $image -Volumes @("$($archiveDirectory):/backup:ro") -Environment @("LEX_RUN_PROFILE=$Profile") -PythonArguments @('-c', $probe, "/backup/$archiveName", $Key)
    if (-not $value) { throw 'Could not read the pinned runtime image from the backup manifest.' }
    return ([string]$value).Trim()
}

function Invoke-Compose([string[]]$Arguments) {
    Push-Location $Repo
    try {
        & docker compose --env-file $EnvFile @ComposeFiles @Arguments
        if ($LASTEXITCODE -ne 0) { throw "docker compose failed with exit code $LASTEXITCODE" }
    } finally { Pop-Location }
}

function Test-ActiveSend {
    $database = Join-Path $AppData 'app.sqlite'
    if (-not (Test-Path $database)) { return }
    $probe = @'
import json, sqlite3, sys
c=sqlite3.connect(sys.argv[1])
try:
 rows=c.execute("select body from records where kind='task'").fetchall()
 active=[]
 for (raw,) in rows:
  x=json.loads(raw)
  if x.get('status') in ('sending','unknown') or x.get('dispatch_status') in ('sending','unknown','outcome_unknown'):
   active.append(x.get('id','unknown'))
 print(json.dumps(active))
finally: c.close()
'@
    $image = Get-SelectedImage
    # The services are stopped and the probe is read-only SQL, but SQLite may
    # need to create WAL/SHM coordination files while opening a WAL database.
    $active = Invoke-PinnedPython -Image $image -Volumes @("$($AppData):/data") -Environment @("LEX_RUN_PROFILE=$Profile") -PythonArguments @('-c', $probe, '/data/app.sqlite')
    if (($active | ConvertFrom-Json).Count -gt 0) { throw 'Active or uncertain dispatch exists; resolve it before upgrade or backup.' }
}

function Test-Host {
    if ($env:OS -ne 'Windows_NT') { throw 'This launcher requires Windows.' }
    if ([Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -notin @('X64','Arm64')) { throw 'Unsupported Windows architecture.' }
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) { throw 'Docker Desktop with the WSL2 backend is required.' }
    & docker info --format '{{.OSType}} {{.Architecture}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running or its engine is unavailable.' }
}

function Test-ReleaseManifest([string]$Image = $null, [string]$ManifestPath = $null) {
    if ($Profile -ne 'production') { return }
    if (-not $ManifestPath) { $ManifestPath = $ProfileManifest }
    if (-not $Image) { $Image = Get-SelectedImage }
    if (-not (Test-Path -Path $ManifestPath -PathType Leaf)) {
        throw 'Production requires the reviewed release-build-manifest.json supplied with the release bundle.'
    }
    $manifestDirectory = Split-Path -Parent (Resolve-Path $ManifestPath).Path
    $manifestName = Split-Path -Leaf $ManifestPath
    $runtimeId = Get-ImageId $Image
    $probe = 'from lexaegis.contracts import ReleaseBuildManifest; import json,sys; x=ReleaseBuildManifest.model_validate_json(open(sys.argv[1],"rb").read()); print(json.dumps({"status":x.status,"digests":x.container_image_digests}))'
    $result = Invoke-PinnedPython -Image $Image -Volumes @("$($manifestDirectory):/release:ro") -Environment @("LEX_RUN_PROFILE=$Profile", 'LEX_RELEASE_BUILD_MANIFEST_PATH=/release/manifest.json') -PythonArguments @('-c', $probe, "/release/$manifestName") | ConvertFrom-Json
    if ($result.status -ne 'verified') { throw 'The production release build manifest is not valid and verified.' }
    foreach ($role in @('api','worker','gateway')) {
        if ($result.digests.$role -ne $runtimeId) { throw "Selected runtime image ID does not match manifest role $role." }
    }
}

Test-Host
# Validate start candidates before Write-EnvFile can persist a changed image.
if ($Action -eq 'start') {
    $startImage = $RequestedReleaseImage
    if (-not $startImage) { $startImage = Get-ConfiguredValue 'LEX_RELEASE_IMAGE' }
    if (-not $startImage) { $startImage = 'lexaegis:local' }
    $startRouteImage = $RequestedRouteImage
    if (-not $startRouteImage) { $startRouteImage = Get-ConfiguredValue 'LEX_ROUTE_IMAGE' }
    if (-not $startRouteImage) { throw 'Specify the exact locally loaded route-isolation image using -RouteImage.' }
    if ($Profile -eq 'production' -and -not $RequestedReleaseImage) { throw 'Production requires -ReleaseImage with the reviewed release image reference.' }
    $startManifest = $ProfileManifest
    if ($RequestedReleaseManifest -and (Test-Path -Path $RequestedReleaseManifest -PathType Leaf)) {
        $startManifest = $RequestedReleaseManifest
    } elseif (-not (Test-Path -Path $ProfileManifest -PathType Leaf) -and (Test-Path -Path $ReleaseManifest -PathType Leaf)) {
        $startManifest = $ReleaseManifest
    }
    Test-ReleaseManifest -Image $startImage -ManifestPath $startManifest
    Assert-ImageMatchesDelivery -Image $startImage -Key 'runtime_image_id'
    Assert-ImageMatchesDelivery -Image $startRouteImage -Key 'route_image_id'
}
# Upgrade backup must describe the currently running release image. Defer the
# requested image update until after that backup has been created.
if ($Action -in @('upgrade','rollback') -and (Test-Path $EnvFile) -and $RequestedReleaseImage) {
    $ReleaseImage = $null
}
if ($Action -in @('upgrade','rollback') -and (Test-Path $EnvFile) -and $RequestedRouteImage) {
    $RouteImage = $null
}
if ($Action -eq 'start' -and (Test-Path $EnvFile)) {
    # Existing profile values remain authoritative until candidate validation
    # completes in the start branch below.
    $ReleaseImage = $null
    $RouteImage = $null
}
Write-EnvFile
switch ($Action) {
    'init' { Invoke-Compose -Arguments @('config','--quiet'); Write-Output "Initialized isolated $Profile profile at $DataRoot" }
    'start' {
        $selectedImage = $RequestedReleaseImage
        if (-not $selectedImage) { $selectedImage = Get-ConfiguredValue 'LEX_RELEASE_IMAGE' }
        if (-not $selectedImage) { $selectedImage = 'lexaegis:local' }
        if ($Profile -eq 'production' -and -not $RequestedReleaseImage) { throw 'Production requires -ReleaseImage with the reviewed release image reference.' }
        $activeManifest = $ProfileManifest
        if ($RequestedReleaseManifest -and (Test-Path -Path $RequestedReleaseManifest -PathType Leaf)) { $activeManifest = $RequestedReleaseManifest }
        Test-ReleaseManifest -Image $selectedImage -ManifestPath $activeManifest
        $routeImage = $RequestedRouteImage
        if (-not $routeImage) { $routeImage = Get-ConfiguredValue 'LEX_ROUTE_IMAGE' }
        if (-not $routeImage) { throw 'Specify the exact locally loaded route-isolation image using -RouteImage.' }
        Assert-ImageMatchesDelivery -Image $selectedImage -Key 'runtime_image_id'
        Assert-ImageMatchesDelivery -Image $routeImage -Key 'route_image_id'
        if ($activeManifest -ne $ProfileManifest) { Copy-Item -LiteralPath $activeManifest -Destination $ProfileManifest -Force }
        Set-ConfiguredValue 'LEX_RELEASE_IMAGE' (Get-ImageId $selectedImage)
        Set-ConfiguredValue 'LEX_ROUTE_IMAGE' (Get-ImageId $routeImage)
        Invoke-Compose -Arguments @('up','-d','--no-build')
        Write-Output "LexAegis $($Profile): http://127.0.0.1:$ApiPort"
    }
    'stop' { Invoke-Compose -Arguments @('stop') }
    'doctor' {
        Test-ReleaseManifest
        Invoke-Compose -Arguments @('config','--quiet')
        & docker info --format 'Docker={{.ServerVersion}} OS={{.OSType}} Arch={{.Architecture}}'
        if ($LASTEXITCODE -ne 0) { throw 'Docker health check failed.' }
        Write-Output "Profile=$Profile Data=$DataRoot"
        Write-Output 'Secrets are configured and will not be printed.'
    }
    'backup' {
        Invoke-Compose -Arguments @('stop')
        Test-ActiveSend
        if (-not $Archive) { throw 'Specify -Archive for the new backup file.' }
        $parent = Split-Path -Parent $Archive
        if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
        if ([IO.Path]::IsPathRooted($Archive)) { $destination = $Archive }
        else { $destination = Join-Path $Repo $Archive }
        Invoke-Maintenance -Arguments @('backup', $destination, '--offline-confirm', '--profile', $Profile)
    }
    'restore' {
        if (-not $Archive) { throw 'Specify -Archive.' }
        Invoke-Compose -Arguments @('stop')
        Test-ActiveSend
        $restoreImage = Get-BackupValue $Archive 'release_image'
        $restoreRouteImage = Get-BackupValue $Archive 'route_image'
        if ($Profile -eq 'production' -and -not $restoreImage) { throw 'Backup has no pinned production image.' }
        if ($restoreImage) {
            if ((Get-ImageId $restoreImage) -ne $restoreImage) { throw 'Backup must name the immutable release image ID.' }
        }
        if ($restoreRouteImage) {
            if ((Get-ImageId $restoreRouteImage) -ne $restoreRouteImage) { throw 'Backup must name the immutable route image ID.' }
        }
        $maintenanceImage = $restoreImage
        if (-not $maintenanceImage) { $maintenanceImage = Get-SelectedImage }
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $savedApp = Join-Path $DataRoot "app-before-restore-$stamp"
        $savedGateway = Join-Path $DataRoot "gateway-before-restore-$stamp"
        if (Test-Path $AppData) { Move-Item $AppData $savedApp }
        if (Test-Path $GatewayData) { Move-Item $GatewayData $savedGateway }
        New-Item -ItemType Directory -Force -Path $AppData,$GatewayData | Out-Null
        try {
            Invoke-Maintenance -Arguments @('restore', $Archive, '--target', $AppData, '--gateway-target', $GatewayData, '--profile', $Profile) -Image $maintenanceImage
        } catch {
            Remove-Item -Recurse -Force $AppData,$GatewayData
            Move-Item $savedApp $AppData
            Move-Item $savedGateway $GatewayData
            throw 'Restore failed; previous profile data directories were restored.'
        }
        if ($restoreImage) { Set-ConfiguredValue 'LEX_RELEASE_IMAGE' $restoreImage }
        if ($restoreRouteImage) { Set-ConfiguredValue 'LEX_ROUTE_IMAGE' $restoreRouteImage }
    }
    'upgrade' {
        if ($Profile -eq 'production' -and -not $RequestedReleaseImage) { throw 'Production upgrade requires a reviewed -ReleaseImage reference.' }
        if (-not $RequestedRouteImage) { throw 'Upgrade requires the exact -RouteImage from the reviewed delivery bundle.' }
        Assert-ImageMatchesDelivery -Image $RequestedReleaseImage -Key 'runtime_image_id'
        Assert-ImageMatchesDelivery -Image $RequestedRouteImage -Key 'route_image_id'
        Test-ReleaseManifest -Image $RequestedReleaseImage -ManifestPath $ReleaseManifest
        Invoke-Compose -Arguments @('stop')
        Test-ActiveSend
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $pre = Join-Path $DataRoot "pre-upgrade-$stamp.lexbackup"
        Invoke-Maintenance -Arguments @('backup', $pre, '--offline-confirm', '--profile', $Profile)
        $ReleaseImage = $RequestedReleaseImage
        $RouteImage = $RequestedRouteImage
        if (Test-Path -Path $ReleaseManifest -PathType Leaf) { Copy-Item -LiteralPath $ReleaseManifest -Destination $ProfileManifest -Force }
        if ($ReleaseImage) { Write-EnvFile }
        $selectedImage = $ReleaseImage
        if (-not $selectedImage) { $selectedImage = 'lexaegis:local' }
        if ($Profile -eq 'production' -and -not $ReleaseImage) { throw 'Production upgrade requires a reviewed -ReleaseImage reference.' }
        & docker image inspect $selectedImage | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Selected release image is not present locally; upgrade cancelled.' }
        $routeImage = Get-ImageId $RequestedRouteImage
        Set-ConfiguredValue 'LEX_RELEASE_IMAGE' (Get-ImageId $selectedImage)
        Set-ConfiguredValue 'LEX_ROUTE_IMAGE' $routeImage
        Test-ReleaseManifest -Image $selectedImage -ManifestPath $ProfileManifest
        Invoke-Compose -Arguments @('up','-d','--no-build')
        Write-Output "Pre-upgrade backup: $pre"
    }
    'rollback' {
        if (-not $Archive) { throw 'Specify the pre-upgrade backup with -Archive.' }
        Invoke-Compose -Arguments @('stop')
        Test-ActiveSend
        $oldImage = Get-BackupValue $Archive 'release_image'
        $oldRouteImage = Get-BackupValue $Archive 'route_image'
        if ($Profile -eq 'production' -and -not $oldImage) { throw 'Backup has no pinned production image; rollback cannot select a verified release.' }
        if ($oldImage) {
            if ((Get-ImageId $oldImage) -ne $oldImage) { throw 'Backup must name the immutable release image ID.' }
        }
        $routeImage = $oldRouteImage
        if (-not $routeImage) { throw 'Backup has no pinned route-isolation image; rollback cannot select a verified release.' }
        if ((Get-ImageId $routeImage) -ne $routeImage) { throw 'Backup must name the immutable route image ID.' }
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $savedApp = Join-Path $DataRoot "app-after-upgrade-$stamp"
        $savedGateway = Join-Path $DataRoot "gateway-after-upgrade-$stamp"
        if (Test-Path $AppData) { Move-Item $AppData $savedApp }
        if (Test-Path $GatewayData) { Move-Item $GatewayData $savedGateway }
        New-Item -ItemType Directory -Force -Path $AppData,$GatewayData | Out-Null
        try {
            Invoke-Maintenance -Arguments @('restore', $Archive, '--target', $AppData, '--gateway-target', $GatewayData, '--profile', $Profile) -Image $oldImage
        } catch {
            Remove-Item -Recurse -Force $AppData,$GatewayData
            Move-Item $savedApp $AppData
            Move-Item $savedGateway $GatewayData
            throw 'Rollback restore failed; previous data directories were restored.'
        }
        if ($oldImage) { Set-ConfiguredValue 'LEX_RELEASE_IMAGE' $oldImage }
        if ($oldRouteImage) { Set-ConfiguredValue 'LEX_ROUTE_IMAGE' $oldRouteImage }
        Invoke-Compose -Arguments @('up','-d','--no-build')
    }
}
