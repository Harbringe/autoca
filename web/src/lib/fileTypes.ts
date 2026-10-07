// The kinds of file a client may send for reading: bank statements and invoices as a PDF, an Excel sheet, a CSV, a Word
// file, or a photo or scan. The server decides what a file really is from its bytes; this only keeps the file picker and
// the first check honest.

export const ACCEPT = '.pdf,.xlsx,.csv,.docx,.jpg,.jpeg,.png,.webp,.tif,.tiff,application/pdf,image/*'
export const ACCEPTED_NAME = /\.(pdf|xlsx|csv|docx|jpe?g|png|webp|tiff?)$/i
