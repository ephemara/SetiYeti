$py = 'C:\scoop\shims\python.exe'
$wd = 'E:\SetiYeti'
$jobs = @(
  @{raw='data\blc04_guppi_57807_75725_DIAG_TRAPPIST1_0015.0000.raw'; pol='0'; out='runs\baseline_v2_0015_p0.csv'; log='runs\baseline_v2_0015_p0.log'},
  @{raw='data\blc04_guppi_57807_75725_DIAG_TRAPPIST1_0015.0000.raw'; pol='1'; out='runs\baseline_v2_0015_p1.csv'; log='runs\baseline_v2_0015_p1.log'},
  @{raw='data\blc04_guppi_57807_75805_DIAG_TRAPPIST1_OFF_0016.0000.raw';       pol='0'; out='runs\baseline_v2_0016_p0.csv'; log='runs\baseline_v2_0016_p0.log'},
  @{raw='data\blc04_guppi_57807_75805_DIAG_TRAPPIST1_OFF_0016.0000.raw';       pol='1'; out='runs\baseline_v2_0016_p1.csv'; log='runs\baseline_v2_0016_p1.log'}
)
foreach ($j in $jobs) {
  Start-Process -FilePath $py -ArgumentList @(
    'python\mvp_scan.py', '--raw', $j.raw, '--b0', '0', '--b1', '127',
    '--chans', '0-63', '--pol', $j.pol, '--out', $j.out, '--workers', '1'
  ) -WorkingDirectory $wd `
    -RedirectStandardOutput (Join-Path $wd $j.log) `
    -RedirectStandardError  (Join-Path $wd ($j.log + '.err')) `
    -WindowStyle Hidden
  Write-Output ("launched: " + $j.out)
}
