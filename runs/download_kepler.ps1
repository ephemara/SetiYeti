$wd = 'E:\SetiYeti'
$aria = 'C:\scoop\shims\aria2c.exe'
$jobs = @(
  @{url='http://blpd1.ssl.berkeley.edu/kepler160_092020/blc44_guppi_59103_01984_DIAG_KEPLER-160_0010.0000.raw'; log='runs\dl_kepler_on.log'},
  @{url='http://blpd1.ssl.berkeley.edu/kepler160_092020/blc44_guppi_59103_02170_DIAG_KEPLER-160_OFF_0011.0000.raw'; log='runs\dl_kepler_off.log'}
)
foreach ($j in $jobs) {
  Start-Process -FilePath $aria -ArgumentList @(
    '-x','8','-s','8','-c','--file-allocation=none',
    '--summary-interval=15','--console-log-level=warn',
    $j.url, '-d', 'data'
  ) -WorkingDirectory $wd `
    -RedirectStandardOutput (Join-Path $wd $j.log) `
    -RedirectStandardError  (Join-Path $wd ($j.log + '.err')) `
    -WindowStyle Hidden
  Write-Output ("launched download: " + $j.url.Split('/')[-1])
}
