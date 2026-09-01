export function parseModalTokenCommand(command: string) {
  const tokenId = command.match(/--token-id(?:=|\s+)["']?([^\s"']+)/)?.[1]
  const tokenSecret = command.match(/--token-secret(?:=|\s+)["']?([^\s"']+)/)?.[1]
  const workspace = command.match(/--profile(?:=|\s+)["']?([^\s"']+)/)?.[1]
  return tokenId && tokenSecret && workspace ? { tokenId, tokenSecret, workspace } : null
}
