Get-ScheduledTask | Where-Object { $_.TaskName -like "MyAgents_WorkReportAssist*" } | Get-ScheduledTaskInfo
