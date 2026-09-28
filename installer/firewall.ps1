# Windows Firewall rules for the Minecraft Server Control agent.
# Run in an Administrator PowerShell:  .\installer\firewall.ps1
#
# This does NOT disable the firewall. It creates one narrow inbound rule that
# allows the dashboard port only from the Tailscale CGNAT range (100.64.0.0/10),
# which is the only range your tailnet peers can come from. Anything arriving
# from your LAN or from the internet is still blocked by the default policy.

param(
    [int]$Port = 8765,
    [int]$RedirectPort = 8080,
    [switch]$Remove
)

$RuleName  = "Minecraft Server Control (HTTPS, Tailscale only)"
$RedirName = "Minecraft Server Control (HTTP redirect, Tailscale only)"

if ($Remove) {
    Remove-NetFirewallRule -DisplayName $RuleName  -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -DisplayName $RedirName -ErrorAction SilentlyContinue
    Write-Host "Removed the Minecraft Server Control firewall rules."
    exit 0
}

Remove-NetFirewallRule -DisplayName $RuleName  -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName $RedirName -ErrorAction SilentlyContinue

New-NetFirewallRule `
    -DisplayName $RuleName `
    -Description "Allows the control dashboard over HTTPS from Tailscale peers only." `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
    -RemoteAddress 100.64.0.0/10 `
    -Profile Any | Out-Null

New-NetFirewallRule `
    -DisplayName $RedirName `
    -Description "Allows the HTTP listener that only redirects to HTTPS, from Tailscale peers only." `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort $RedirectPort `
    -RemoteAddress 100.64.0.0/10 `
    -Profile Any | Out-Null

Write-Host ""
Write-Host "Created two inbound rules:"
Write-Host "  $RuleName"
Write-Host "    TCP $Port, remote address 100.64.0.0/10 (Tailscale only)"
Write-Host "  $RedirName"
Write-Host "    TCP $RedirectPort, remote address 100.64.0.0/10 (Tailscale only)"
Write-Host ""
Write-Host "Nothing was opened to your LAN or to the internet, and the firewall"
Write-Host "itself remains enabled. Verify with:"
Write-Host "  Get-NetFirewallRule -DisplayName '$RuleName' | Get-NetFirewallAddressFilter"
Write-Host ""
Write-Host "To remove the rules later:  .\installer\firewall.ps1 -Remove"
