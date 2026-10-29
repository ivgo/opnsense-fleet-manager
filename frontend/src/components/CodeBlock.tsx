import { useState } from "react";
import { Box, IconButton, Paper, Stack, Tooltip, Typography } from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import CheckIcon from "@mui/icons-material/Check";

import { copyToClipboard } from "@/utils/format";
import { monoFont } from "@/theme";

export interface CodeBlockProps {
  code: string;
  language?: string;
  maxHeight?: number;
  title?: string;
  showCopy?: boolean;
  wrap?: boolean;
}

export function CodeBlock({
  code,
  language,
  maxHeight = 420,
  title,
  showCopy = true,
  wrap = false,
}: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await copyToClipboard(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <Paper variant="outlined" sx={{ overflow: "hidden", bgcolor: "action.hover" }}>
      {(title || showCopy) && (
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          sx={{ px: 1.5, py: 0.5, borderBottom: 1, borderColor: "divider" }}
        >
          <Typography variant="caption" color="text.secondary" sx={{ fontFamily: monoFont }}>
            {title ?? language ?? "code"}
          </Typography>
          {showCopy && (
            <Tooltip title={copied ? "Copied" : "Copy to clipboard"}>
              <IconButton size="small" onClick={handleCopy} aria-label="Copy code">
                {copied ? <CheckIcon fontSize="small" color="success" /> : <ContentCopyIcon fontSize="small" />}
              </IconButton>
            </Tooltip>
          )}
        </Stack>
      )}
      <Box
        component="pre"
        sx={{
          m: 0,
          p: 1.75,
          overflow: "auto",
          maxHeight,
          fontSize: 12.5,
          lineHeight: 1.55,
          fontFamily: monoFont,
          whiteSpace: wrap ? "pre-wrap" : "pre",
          wordBreak: wrap ? "break-word" : "normal",
        }}
      >
        {code}
      </Box>
    </Paper>
  );
}

export default CodeBlock;
