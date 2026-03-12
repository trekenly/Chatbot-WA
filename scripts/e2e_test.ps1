<# scripts\e2e_test.ps1 - BusX Chatbot E2E test (PS 5.1 + PS 7+) - SINGLE PAX #>

param(
  [string]$BaseUrl = "http://127.0.0.1:8000/chat",
  [int]$Pax = 1,

  # 0 = auto pick a trip with enough seats
  [int]$TripChoice = 0,

  [switch]$SkipPay
)

$ErrorActionPreference = "Stop"

# ---- UTF-8 console output (best-effort for PS 5.1 + PS 7) ----
try { chcp 65001 | Out-Null } catch { }
try {
  $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
  $OutputEncoding = $utf8NoBom
  [Console]::OutputEncoding = $utf8NoBom
} catch { }
# ------------------------------------------------------------

$uid = "e2e-" + [guid]::NewGuid().ToString("N")
Write-Host "UID = $uid"

function Send-Chat([string]$text) {
  $body = @{ user_id = $uid; text = $text } | ConvertTo-Json -Depth 50 -Compress

  $iwParams = @{
    Uri         = $BaseUrl
    Method      = 'Post'
    ContentType = 'application/json'
    Headers     = @{ Accept = 'application/json' }
    Body        = $body
    ErrorAction = 'Stop'
  }

  if ((Get-Command Invoke-WebRequest).Parameters.ContainsKey('UseBasicParsing')) {
    $iwParams['UseBasicParsing'] = $true
  }

  $resp = Invoke-WebRequest @iwParams
  if (-not $resp) { throw "No response from $BaseUrl" }

  # Prefer raw-bytes -> UTF-8 decode (fixes PS 5.1 charset weirdness)
  $jsonText = $null
  try {
    if ($resp.RawContentStream) {
      try { $resp.RawContentStream.Position = 0 } catch { }
      $ms = New-Object System.IO.MemoryStream
      try {
        $resp.RawContentStream.CopyTo($ms)
        $bytes = $ms.ToArray()
        $jsonText = [System.Text.Encoding]::UTF8.GetString($bytes)
      } finally {
        $ms.Dispose()
      }
    }
  } catch {
    $jsonText = $null
  }

  if (-not $jsonText) {
    if (-not $resp.Content) { throw "No response content from $BaseUrl" }
    $jsonText = $resp.Content
  }

  return ($jsonText | ConvertFrom-Json)
}

function Show-Actions($resp) {
  if (-not $resp -or -not $resp.actions) { return }

  foreach ($a in $resp.actions) {
    switch ($a.type) {
      "say"        { Write-Host ("SAY: " + $a.payload.text) }
      "ask"        { Write-Host ("ASK(" + $a.payload.field + "): " + $a.payload.prompt) }
      "choose_one" {
        Write-Host ("CHOOSE: " + $a.payload.title)
        foreach ($opt in $a.payload.options) { Write-Host ("  " + $opt.label) }
      }
      default      { Write-Host ("ACTION: " + $a.type) }
    }
  }
}

function Show-State($resp) {
  $s = $resp.state
  if (-not $s) { Write-Host "(no state)"; return }
  $seats = if ($s.selected_seats) { ($s.selected_seats -join ",") } else { "" }
  $evs   = if ($s.seat_event_ids) { ($s.seat_event_ids -join ",") } else { "" }

  Write-Host ("STATE step={0} reservation_id={1} order_ref_id={2} seats=[{3}] seat_event_ids=[{4}]" -f `
    $s.step, $s.reservation_id, $s.order_ref_id, $seats, $evs)
}

function Get-ChooseOptions($resp) {
  if (-not $resp.actions) { return @() }
  foreach ($a in $resp.actions) {
    if ($a.type -eq "choose_one" -and $a.payload -and $a.payload.options) {
      return @($a.payload.options)
    }
  }
  return @()
}

function Extract-SeatsFromLabel([string]$label) {
  # label contains "... | seats 21"
  $m = [regex]::Match($label, '(?i)\bseats\s+(\d+)\b')
  if ($m.Success) { return [int]$m.Groups[1].Value }
  return $null
}

function Assert-Step($resp, [string]$expected, [string]$context) {
  if (-not $resp -or -not $resp.state) {
    throw "Expected state in response ($context), but got none."
  }
  $actual = [string]$resp.state.step
  if ($actual -ne $expected) {
    throw "Expected step=$expected after $context, got step=$actual"
  }
}

function Assert-StepOneOf($resp, [string[]]$expected, [string]$context) {
  if (-not $resp -or -not $resp.state) {
    throw "Expected state in response ($context), but got none."
  }
  $actual = [string]$resp.state.step
  if ($expected -notcontains $actual) {
    throw "Expected step in @($($expected -join ',')) after $context, got step=$actual"
  }
}

# -----------------------------
# MAIN FLOW (single pax)
# -----------------------------

Write-Host "---- reset ----"
$r = Send-Chat "reset"
Show-Actions $r
Show-State $r
Assert-Step $r "NEW" "reset"

$tomorrow = (Get-Date).AddDays(1).ToString("yyyy-MM-dd")
Write-Host "---- date+pax ----"
$r = Send-Chat "$tomorrow $Pax pax"
Show-Actions $r
Show-State $r

$options = Get-ChooseOptions $r
if (-not $options -or $options.Count -lt 1) {
  throw "Expected choose_one options from bot, but none found."
}

if ($TripChoice -le 0) {
  # Auto pick first option with enough seats (>= 1)
  $picked = $null
  for ($i=0; $i -lt $options.Count; $i++) {
    $se = Extract-SeatsFromLabel $options[$i].label
    if ($se -ne $null -and $se -ge $Pax) {
      $picked = $i + 1
      break
    }
  }
  if (-not $picked) {
    throw "No trip option has >= $Pax seats."
  }
  $TripChoice = $picked
  Write-Host "Auto-picked TripChoice=$TripChoice" -ForegroundColor Cyan
}

Write-Host "---- pick trip ----"
$r = Send-Chat ([string]$TripChoice)
Show-Actions $r
Show-State $r
Assert-StepOneOf $r @("CONFIRM","PICK_TRIP") "pick trip"

Write-Host "---- confirm ----"
$r = Send-Chat "confirm"
Show-Actions $r
Show-State $r
Assert-Step $r "PICK_SEATS" "confirm"

$avail = $r.state.available_seats
if (-not $avail -or $avail.Count -lt $Pax) {
  throw "Not enough available_seats in state to auto-pick."
}

# SINGLE SEAT PICK
$seatPick = [string]$avail[0]

Write-Host "---- seats ($seatPick) ----"
$r = Send-Chat $seatPick
Show-Actions $r
Show-State $r
Assert-Step $r "READY" "seats"

Write-Host "---- mark ----"
$r = Send-Chat "mark"
Show-Actions $r
Show-State $r
Assert-Step $r "MARKED" "mark"

Write-Host "---- reserve ----"
$r = Send-Chat "reserve"
Show-Actions $r
Show-State $r
Assert-Step $r "RESERVED" "reserve"

if ($SkipPay) {
  Write-Host "DONE (SkipPay enabled)." -ForegroundColor Green
  exit 0
}

Write-Host "---- pay ----"
$r = Send-Chat "pay"
Show-Actions $r
Show-State $r

# If your environment sometimes only reaches PAYMENT_PENDING (no provider completion),
# accept either PAID or PAYMENT_PENDING here.
Assert-StepOneOf $r @("PAID","PAYMENT_PENDING") "pay"

Write-Host "---- status (post-pay) ----"
$r = Send-Chat "status"
Show-Actions $r
Show-State $r

# In the "instant pay" sandbox, expect PAID. In real provider flows, status may remain PAYMENT_PENDING.
Assert-StepOneOf $r @("PAID","PAYMENT_PENDING") "status (post-pay)"

Write-Host "DONE" -ForegroundColor Green
