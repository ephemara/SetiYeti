$py = 'C:\scoop\shims\python.exe'
$wd = 'E:\SetiYeti'
Start-Process -FilePath $py -ArgumentList @(
  'python\longhaul.py',
  '--on',  'data\blc44_guppi_59103_01984_DIAG_KEPLER-160_0010.0000.raw',
  '--off', 'data\blc44_guppi_59103_02170_DIAG_KEPLER-160_OFF_0011.0000.raw',
  '--target', 'KEPLER160',
  '--outdir', 'runs/longhaul_kepler',
  '--pols', '0,1,2,3',
  '--jerk-pols', '0,1',
  '--topk', '25'
) -WorkingDirectory $wd `
  -RedirectStandardOutput 'E:\SetiYeti\runs\longhaul_boot.log' `
  -RedirectStandardError  'E:\SetiYeti\runs\longhaul_boot.err' `
  -WindowStyle Hidden
Write-Output 'longhaul launched'
