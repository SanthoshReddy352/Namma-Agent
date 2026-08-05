$bytes = [System.IO.File]::ReadAllBytes('C:\Users\santh\Desktop\Sripa Aqua\sripa_fb_profile_pic.jpg')
Write-Host ($bytes[0].ToString() + " " + $bytes[1].ToString() + " " + $bytes[2].ToString())
