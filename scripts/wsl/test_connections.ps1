$ErrorActionPreference = 'Stop'

$maria = Test-NetConnection -ComputerName 127.0.0.1 -Port 3306 -WarningAction SilentlyContinue
$redis = Test-NetConnection -ComputerName 127.0.0.1 -Port 6379 -WarningAction SilentlyContinue

if (-not $maria.TcpTestSucceeded) { throw 'MariaDB is not reachable on localhost:3306.' }
if (-not $redis.TcpTestSucceeded) { throw 'Redis is not reachable on localhost:6379.' }

Write-Output 'MariaDB and Redis are reachable from Windows.'
