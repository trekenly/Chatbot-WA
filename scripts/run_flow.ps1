<# run_flow.ps1 - simple end-to-end driver (PS 5.1 + PS 7+) #>

param(
  # Use base host OR full /chat URL. Both supported.
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [string]$UserId = ("e2e-" + [guid]::NewGuid().ToString("N")),

  [string]$DepartureDate = "",
  [int]$Pax = 2,

  [int]$TripChoice = 1,

  # If empty, seats will auto-pick from state.available_seats after "confirm"
  [string]$Seat = "",

  # Commands to run
  [switch]$DoReset,
  [switch]$OnlyStep1,
  [switch]$ShowDetails,

  # Poll status after pay (0 disables)
  [int]$StatusPolls = 0,
  [int]$StatusSleepSeconds = 2
)

$ErrorActionPreference = "Stop"

function Resolve-ChatUrl([string]$url) {
  $u = $url.TrimEnd("/")
  if ($u.ToLower().EndsWith("/chat")) { return $u }
  return ($u + "/chat")
}

$ChatUrl = Resolve-ChatUrl $BaseUrl

function Post-Chat([string]$text) {
  $bodyObj = @{ user_id = $UserId; text = $text }
  $body = $bodyObj | ConvertTo-Json -Depth 50

  $irmParams = @{
    Uri         = $ChatUrl
    Method      = 'Post'
    ContentType = 'application/json'
    Body        = $body
    ErrorAction = 'Stop'
  }

  try {
    return (Invoke-RestMethod @irmParams)
  } catch {
    # If server returned non-JSON, try to show raw body for debugging
    $resp = $_.Exception.Response
    if ($resp -and $resp.GetResponseStream()) {
      try {
        $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
        $raw = $sr.ReadToEnd()
        if ($raw) {
          Write-Host "---- RAW RESPONSE ----" -ForegroundColor Yellow
          Write-Host $raw
          Write-Host "----------------------" -ForegroundColor Yellow
        }
      } catch {}
    }
    throw "HTTP request failed: $($_.Exception.Message)"
  }
}

function Show-Actions($json) {
  if ($null -eq $json -or $null -eq $json.actions) { return }
  foreach ($a in $json.actions) {
    $t = [string]$a.type
    switch ($t) {
      "say" {
        Write-Host ("BOT: " + $a.payload.text)
      }
      "ask" {
        Write-Host ("BOT ASK[" + $a.payload.field + "]: " + $a.payload.prompt)
      }
      "choose_one" {
        Write-Host ("BOT: " + $a.payload.title)
        foreach ($opt in $a.payload.options) {
          Write-Host ("  " + $opt.label)
        }
      }
      default {
        Write-Host ("BOT ACTION: " + $t)
      }
    }
  }
}

function Show-State($json) {
  if ($null -eq $json -or $null -eq $json.state) { return }
  $s = $json.state
  $seats = if ($s.selected_seats) { ($s.selected_seats -join ",") } else { "" }
  $evs   = if ($s.seat_event_ids) { ($s.seat_event_ids -join ",") } else { "" }

  Write-Host ("STATE: step={0} reservation_id={1} order_ref_id={2} seats=[{3}] seat_event_ids=[{4}]" -f `
    $s.step, $s.reservation_id, $s.order_ref_id, $seats, $evs)
}

function Require-Step($json, [string]$want, [string]$context) {
  $got = ""
  if ($json -and $json.state) { $got = [string]$json.state.step }
  if ($got -ne $want) {
    Write-Host "Unexpected step after $context. want=$want got=$got" -ForegroundColor Yellow
  }
}

Write-Host "Chat URL = $ChatUrl"
Write-Host "UserId   = $UserId"

# Optional reset first (recommended)
if ($DoReset) {
  $json = Post-Chat "reset"
  Show-Actions $json
  Show-State $json
}

# If date not provided, default to tomorrow
if (-not $DepartureDate) {
  $DepartureDate = (Get-Date).AddDays(1).ToString("yyyy-MM-dd")
}

# 0) start search (date+pax in one message)
$json = Post-Chat ("$DepartureDate $Pax pax")
Show-Actions $json
Show-State $json
Require-Step $json "PICK_TRIP" "search"

# 1) pick trip
$json = Post-Chat ([string]$TripChoice)
Show-Actions $json
Show-State $json
Require-Step $json "CONFIRM" "pick trip"

# 2) confirm seat layout
$json = Post-Chat "confirm"
Show-Actions $json
Show-State $json
Require-Step $json "PICK_SEATS" "confirm"

# 3) pick seat(s)
# If Seat is empty, auto-pick first N seats from state.available_seats
if (-not $Seat) {
  $avail = $json.state.available_seats
  if (-not $avail -or $avail.Count -lt $Pax) {
    throw "Not enough available_seats in state to auto-pick. available_count=$($avail.Count) pax=$Pax"
  }
  $Seat = (($avail | Select-Object -First $Pax) -join " ")
  Write-Host ("Auto-picked seats: " + $Seat) -ForegroundColor Cyan
}

$json = Post-Chat $Seat
Show-Actions $json
Show-State $json
Require-Step $json "READY" "pick seats"

# 4) Step 1: mark seats
$json = Post-Chat "mark"
Show-Actions $json
Show-State $json
Require-Step $json "MARKED" "mark"

if ($OnlyStep1) {
  Write-Host ""
  Write-Host "Done: Step 1 completed (mark_seats)." -ForegroundColor Green
  exit 0
}

# 5) Step 2: create reservation
$json = Post-Chat "reserve"
Show-Actions $json
Show-State $json
Require-Step $json "RESERVED" "reserve"

# 6) Step 3: create payment
$json = Post-Chat "pay"
Show-Actions $json
Show-State $json
# Often becomes PAYMENT_PENDING
# Require-Step $json "PAYMENT_PENDING" "pay"

if ($ShowDetails) {
  Write-Host "---- details ----" -ForegroundColor Cyan
  $d = Post-Chat "details"
  Show-Actions $d
  Show-State $d
}

if ($StatusPolls -gt 0) {
  Write-Host "---- status polling ----" -ForegroundColor Cyan
  for ($i=1; $i -le $StatusPolls; $i++) {
    Start-Sleep -Seconds $StatusSleepSeconds
    Write-Host ("poll #" + $i)
    $sr = Post-Chat "status"
    Show-Actions $sr
    Show-State $sr
    if ($sr.state -and $sr.state.step -eq "PAID") {
      Write-Host "✅ PAID detected." -ForegroundColor Green
      break
    }
  }
}

Write-Host ""
Write-Host "Done: Step 1-3 completed." -ForegroundColor Green
