on run
	set desktopAppPath to POSIX path of (path to home folder) & "Applications/Eve.app"
	try
		do shell script "open " & quoted form of desktopAppPath & " >/dev/null 2>&1 &"
	on error
		set helperPath to POSIX path of (path to home folder) & ".eve_runtime/bin/eve_control.sh"
		do shell script quoted form of helperPath & " open >/dev/null 2>&1 &"
	end try
end run
