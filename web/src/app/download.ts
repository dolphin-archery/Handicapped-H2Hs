/**
 * Offer a file to the user through a Blob and a temporary `<a download>` link
 * (deploymentConstrains 3, rule 5). Nothing leaves the device.
 *
 * @param filename - The suggested file name.
 * @param content - The file's text, or its bytes.
 * @param mimeType - The content type, e.g. "application/json".
 */
export function downloadFile(
  filename: string,
  content: string | Uint8Array,
  mimeType: string,
): void {
  const blob = new Blob([content as BlobPart], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
