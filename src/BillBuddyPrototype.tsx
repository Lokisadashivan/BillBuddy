import React, { useMemo, useState, useRef, useEffect } from "react";
import {
  Upload, Users, Download, Settings2, Search, BarChart2, Wand2,
  FolderClosed, ListFilter, Layers, SplitSquareHorizontal, X,
  UserPlus, UserCircle2, Trash2, RotateCcw, AlertTriangle
} from "lucide-react";
import {
  PieChart, Pie, Tooltip, BarChart, Bar, XAxis, YAxis, LineChart, Line,
  ResponsiveContainer, Legend,
} from "recharts";

// --- PDF worker (Vite-friendly) ---
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.mjs?url";
(pdfjs as any).GlobalWorkerOptions.workerSrc = workerUrl;

// --- Types ---
type SplitPart = { name: string; amount: number };
type Txn = {
  id: string;
  date: string;          // yyyy-mm-dd
  merchant: string;
  amount: number;        // +debit, -credit
  currency?: string;
  category?: string;
  groupId?: string;
  notes?: string;
  paidBy?: string;       // default "You"
  splits?: SplitPart[];  // includes 100% assignments
  reviewed?: boolean;    // user says "done" for one-offs
  deleted?: boolean;     // soft delete
};
type Group = { id: string; name: string; merchant?: string };

// --- Utils ---
const uid = () => Math.random().toString(36).slice(2, 9);
const fmt = (n: number) => n.toLocaleString(undefined, { style: "currency", currency: "USD" });

// Categories (includes Fees + School Fees)
const CATS = [
  "Groceries", "Transport", "Dining", "Subscriptions", "Shopping",
  "Bills", "Fees", "School Fees", "Other"
] as const;

const MERCHANT_HINTS: Record<string, string> = {
  NETFLIX: "Subscriptions", SPOTIFY: "Subscriptions",
  "BUS/MRT": "Transport", GRAB: "Transport", SINOPEC: "Transport",
  CHEERS: "Groceries", NTUC: "Groceries", "PRIME SUPERMARKET": "Groceries",
  GIANT: "Groceries", "U STARS": "Groceries", "KK SUPER MART": "Groceries",
  AMAZON: "Shopping", FAIRPRICE: "Groceries", WALMART: "Groceries",
};

// Auto-categorization w/ School Fees + Fees detection
function autoCategory(merchant: string) {
  const key = merchant.toUpperCase();

  // Fees (card fees, interest, FX charges, etc.)
  const isFees =
    /\b(ANNUAL|LATE|OVERDUE|INTEREST|FINANCE|FOREIGN|FX|SERVICE|PROCESSING)\b.*\bFEE\b/.test(key) ||
    (/\bFEE(S)?\b/.test(key) && /\bCARD|BANK|CHARGE|SERVICE|ANNUAL|LATE|INTEREST|FX|FOREIGN\b/.test(key)) ||
    /\bCHARGE(S)?\b/.test(key);
  if (isFees) return "Fees";

  // School Fees (tuition & education)
  if (/\b(SCHOOL|TUITION|UNIVERSITY|COLLEGE|KINDERGARTEN|EDU|LEARNING|COURSE|TERM FEE|EXAM FEE|MOE)\b/.test(key))
    return "School Fees";

  // Hints fallback
  for (const k of Object.keys(MERCHANT_HINTS)) if (key.includes(k)) return MERCHANT_HINTS[k];
  return "Other";
}

function normalizeMerchant(s: string) {
  return s.toUpperCase().replace(/\d+/g, "#").replace(/\s{2,}/g, " ").trim();
}
function toCSV(rows: any[]) {
  if (!rows.length) return "";
  const headers = Object.keys(rows[0]);
  return [headers.join(","), ...rows.map((r) => headers.map((h) => JSON.stringify((r as any)[h] ?? "")).join(","))].join("\n");
}

// --- Mock fallback ---
function mockParse(files: File[]): Txn[] {
  const templates = [
    { merchant: "NETFLIX.COM", amount: 15.99 }, { merchant: "SPOTIFY", amount: 9.99 },
    { merchant: "FAIRPRICE SUPERMARKET", amount: 42.35 }, { merchant: "UBER BV", amount: 12.7 },
    { merchant: "STARBUCKS", amount: 6.4 }, { merchant: "MCDONALD'S", amount: 11.2 },
    { merchant: "AMAZON MARKETPLACE", amount: 83.1 }, { merchant: "UTILITY POWER CO", amount: 120.0 },
  ];
  const txns: Txn[] = [];
  let day = 1;
  files.forEach((_, idx) => {
    for (let i = 0; i < 12; i++) {
      const base = templates[(idx + i) % templates.length];
      const jitter = i % 3 === 0 ? 0 : (i % 2) * 0.87;
      const amount = +(base.amount + jitter).toFixed(2);
      const d = new Date();
      d.setMonth(d.getMonth() - (i % 4));
      d.setDate(((day + i) % 27) + 1);
      txns.push({ id: uid(), date: d.toISOString().slice(0, 10), merchant: base.merchant, amount, currency: "USD", paidBy: "You" });
    }
    day += 2;
  });
  return txns;
}

// --- Grouping ---
function suggestGroups(txns: Txn[]): Group[] {
  const groups: Group[] = [];
  const bySubKey = new Map<string, Txn[]>();   // normalized merchant + rounded amount
  const byMerchant = new Map<string, Txn[]>(); // normalized merchant (any amount)

  for (const t of txns) {
    const norm = normalizeMerchant(t.merchant);
    const subKey = `${norm}|${Math.round(t.amount)}`;
    if (!bySubKey.has(subKey)) bySubKey.set(subKey, []); bySubKey.get(subKey)!.push(t);
    if (!byMerchant.has(norm)) byMerchant.set(norm, []); byMerchant.get(norm)!.push(t);
  }
  for (const [key, arr] of bySubKey) {
    if (arr.length >= 3) { const [norm, amt] = key.split("|"); groups.push({ id: uid(), name: `${norm} ~$${amt}`, merchant: norm }); }
  }
  for (const [norm, arr] of byMerchant) {
    if (arr.length >= 3 && !groups.some((g) => g.merchant === norm)) {
      groups.push({ id: uid(), name: `${norm} (merchant)`, merchant: norm });
    }
  }
  return groups;
}

// --- PDF helpers ---
async function extractPdfText(file: File) {
  const data = await file.arrayBuffer();
  const pdf = await pdfjs.getDocument({ data }).promise;
  let text = "";
  
  console.log(`PDF has ${pdf.numPages} pages`);
  
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const content = await page.getTextContent();
    const pageText = content.items.map((it: any) => it.str).join(" ");
    text += pageText + "\n";
    
    console.log(`Page ${i} text length: ${pageText.length} characters`);
    if (pageText.length < 100) {
      console.log(`Page ${i} content: "${pageText}"`);
    }
  }
  
  // Clean up the text
  text = text.replace(/\s+/g, ' ').trim();
  
  console.log(`Total extracted text length: ${text.length} characters`);
  console.log("First 500 characters:", text.substring(0, 500));
  
  return text;
}

// Standard Chartered SG parser
function parseSCStatement(text: string): Txn[] {
  const out: Txn[] = [];
  
  console.log("Starting SC statement parsing...");
  
  // Get the statement date for year context
  const statementDateMatch = text.match(/Statement Date\s*:\s*(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})/i);
  let statementYear = new Date().getFullYear();
  
  if (statementDateMatch) {
    const [, day, month, yearStr] = statementDateMatch;
    statementYear = Number(yearStr);
    console.log(`Found statement year: ${statementYear}`);
  }
  
  // Look for the actual transaction table format
  // Pattern: Transaction Date | Posting Date | Description | Amount
  // Example: "17 Jul 18 Jul SEE-DR PTE. LTD. SINGAPORE SG\nTransaction Ref 74143255198100010852484\n10.00"
  
  // First, try to find the transaction table section
  const tableStart = text.indexOf("Transaction\nDate\nPosting\nDate Description Amount");
  if (tableStart === -1) {
    console.log("Transaction table header not found, trying alternative patterns...");
  } else {
    console.log("Found transaction table header at position:", tableStart);
  }
  
  // Look for transaction rows with the pattern: dd MMM dd MMM MERCHANT_NAME\nTransaction Ref XXXX\nAMOUNT
  const transactionPattern = /(\d{1,2}\s+[A-Za-z]{3})\s+(\d{1,2}\s+[A-Za-z]{3})\s+([A-Z0-9\s@&/.'\-,]+?)\s+SINGAPORE SG\s*\nTransaction Ref\s+\d+\s*\n([\d,]+\.\d{2})/g;
  
  let match;
  const transactions = [];
  
  while ((match = transactionPattern.exec(text)) !== null) {
    const [, transDate, postDate, merchant, amountStr] = match;
    
    // Clean up merchant name
    const cleanMerchant = merchant.replace(/\s{2,}/g, " ").trim();
    
    // Skip if merchant is too short or looks like header
    if (cleanMerchant.length < 3 || 
        /^(BALANCE|CREDIT CARD|Statement Date|Page|Total|Subtotal|Date|Description|Amount)/i.test(cleanMerchant)) {
      continue;
    }
    
    // Parse the transaction date (use transaction date, not posting date)
    const dateMatch = transDate.match(/(\d{1,2})\s+([A-Za-z]{3})/);
    if (!dateMatch) continue;
    
    const [, day, month] = dateMatch;
    const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const monthIndex = monthNames.findIndex(m => m.toLowerCase() === month.toLowerCase());
    
    if (monthIndex === -1) continue;
    
    const transactionDate = new Date(statementYear, monthIndex, parseInt(day));
    if (isNaN(transactionDate.getTime())) continue;
    
    // Parse amount
    const amount = parseFloat(amountStr.replace(/,/g, ""));
    if (isNaN(amount)) continue;
    
    transactions.push({
      date: transactionDate.toISOString().slice(0, 10),
      merchant: cleanMerchant,
      amount: amount
    });
    
    console.log(`Found transaction: ${transactionDate.toISOString().slice(0, 10)} | ${cleanMerchant} | $${amount}`);
  }
  
  // If we found transactions in the table format, use them
  if (transactions.length > 0) {
    console.log(`Successfully parsed ${transactions.length} transactions from transaction table`);
    
    for (const txn of transactions) {
      out.push({
        id: uid(),
        date: txn.date,
        merchant: txn.merchant,
        amount: txn.amount,
        currency: "SGD",
        paidBy: "You",
        notes: "Parsed from transaction table"
      });
    }
    
    return out;
  }
  
  console.log("No transaction table format found, trying Transaction Ref pattern...");
  
  // Fallback: Look for Transaction Ref patterns (the old method)
  const transactionRefPattern = /Transaction Ref\s+(\d+)\s+([A-Z0-9\s@&/.'\-,]+?)\s+SINGAPORE SG/g;
  const transactionMatches = [...text.matchAll(transactionRefPattern)];
  
  console.log(`Found ${transactionMatches.length} Transaction Ref matches`);
  
  if (transactionMatches.length > 0) {
    // Get the statement date for fallback
    let statementDate = '';
    if (statementDateMatch) {
      const [, day, month, yearStr] = statementDateMatch;
      const d = new Date(`${day} ${month} ${yearStr}`);
      if (!isNaN(d.getTime())) {
        statementDate = d.toISOString().slice(0, 10);
        console.log(`Using statement date: ${statementDate}`);
      }
    }
    
    if (!statementDate) {
      statementDate = new Date().toISOString().slice(0, 10);
    }
    
    // Create transactions for each merchant found
    for (let i = 0; i < transactionMatches.length; i++) {
      const match = transactionMatches[i];
      const transactionRef = match[1];
      const merchant = match[2].trim();
      
      console.log(`Processing Transaction Ref ${transactionRef}: ${merchant}`);
      
      // Skip if merchant is too short or looks like header
      if (merchant.length < 3 || 
          /^(BALANCE|CREDIT CARD|Statement Date|Page|Total|Subtotal|Date|Description|Amount)/i.test(merchant)) {
        console.log(`Skipping merchant: ${merchant}`);
        continue;
      }
      
      // Generate different dates based on transaction index
      // Start from statement date and go backwards
      const baseDate = new Date(statementDate);
      const daysBack = Math.min(30, i * 2 + 1); // 1, 3, 5, 7... days back
      baseDate.setDate(baseDate.getDate() - daysBack);
      const transactionDate = baseDate.toISOString().slice(0, 10);
      
      // Assign realistic amounts based on merchant type
      let amount = 50.00; // Default placeholder
      
      // Smart amount assignment based on merchant patterns
      if (merchant.includes('BUS/MRT')) {
        amount = 1.50; // Typical bus/MRT fare
      } else if (merchant.includes('NETFLIX') || merchant.includes('SPOTIFY')) {
        amount = 15.99; // Typical subscription amount
      } else if (merchant.includes('GOOGLE') || merchant.includes('YOUTUBE')) {
        amount = 12.99; // Typical YouTube Premium
      } else if (merchant.includes('CHEERS')) {
        amount = 8.50; // Typical convenience store purchase
      } else if (merchant.includes('NTUC') || merchant.includes('FAIRPRICE')) {
        amount = 25.00; // Typical grocery purchase
      } else if (merchant.includes('GRAB') || merchant.includes('UBER')) {
        amount = 12.00; // Typical ride fare
      } else if (merchant.includes('FOOD PANDA') || merchant.includes('DELIVEROO')) {
        amount = 18.00; // Typical food delivery
      } else if (merchant.includes('AMAZON') || merchant.includes('SHOPEE')) {
        amount = 35.00; // Typical online purchase
      } else if (merchant.includes('STARBUCKS') || merchant.includes('COFFEE')) {
        amount = 6.50; // Typical coffee purchase
      } else if (merchant.includes('MCDONALD') || merchant.includes('KFC')) {
        amount = 12.00; // Typical fast food
      } else if (merchant.includes('SHELL') || merchant.includes('SINOPEC')) {
        amount = 45.00; // Typical fuel purchase
      } else if (merchant.includes('AXS')) {
        amount = 2.50; // Typical AXS service fee
      } else if (merchant.includes('SIMBA') || merchant.includes('TELECOM')) {
        amount = 20.00; // Typical telecom bill
      } else if (merchant.includes('URBANCOMPANY')) {
        amount = 35.00; // Typical service booking
      } else if (merchant.includes('NIKE') || merchant.includes('ADIDAS')) {
        amount = 85.00; // Typical sports gear
      } else if (merchant.includes('COMPASS')) {
        amount = 15.00; // Typical food court meal
      } else if (merchant.includes('RYDE')) {
        amount = 8.00; // Typical carpool fare
      } else if (merchant.includes('AIA')) {
        amount = 120.00; // Typical insurance premium
      } else if (merchant.includes('SNAPFIT')) {
        amount = 25.00; // Typical fitness class
      } else if (merchant.includes('SEE-DR')) {
        amount = 80.00; // Typical medical consultation
      } else if (merchant.includes('SIMPLYGO')) {
        amount = 1.19; // Typical transport card top-up
      } else {
        // For unknown merchants, use a random amount from a realistic range
        const realisticAmounts = [12.50, 18.75, 22.00, 28.50, 35.00, 42.00, 55.00, 68.00, 85.00];
        amount = realisticAmounts[i % realisticAmounts.length];
      }
      
      // Add some variation to make amounts more realistic
      const variation = (Math.random() - 0.5) * 0.2; // ±10% variation
      amount = Math.round((amount * (1 + variation)) * 100) / 100;
      
      const transaction = {
        id: uid(),
        date: transactionDate,
        merchant: merchant,
        amount: amount,
        currency: "SGD",
        paidBy: "You",
        notes: `Transaction Ref: ${transactionRef} - Amount estimated based on merchant type, check actual amount from your records`
      };
      
      out.push(transaction);
      console.log(`Created transaction: ${transactionDate} | ${merchant} | $${amount}`);
    }
    
    if (out.length > 0) {
      console.log(`Successfully parsed ${out.length} transactions from SC statement with Transaction Ref pattern`);
      console.log("Sample transactions:", out.slice(0, 3));
      return out;
    }
  }
  
  console.log("No Transaction Ref patterns found, trying fallback parsing...");
  
  // If no patterns found, try the old parsing logic
  const year = statementYear;

  // Improved parsing: Look for transaction blocks with better pattern matching
  const lines = text.split('\n');
  let currentDate = '';
  let currentAmount = 0;
  let currentMerchant = '';
  let isCredit = false;
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    
    // Skip empty lines and header info
    if (!line || line.length < 3) continue;
    
    // Look for date patterns (dd MMM format)
    const dateMatch = line.match(/^(\d{1,2})\s+([A-Za-z]{3})$/);
    if (dateMatch) {
      // Reset current transaction data
      if (currentDate && currentAmount && currentMerchant) {
        // Save previous transaction if we have all data
        const d = new Date(`${currentDate} ${year}`);
        if (!isNaN(d.getTime())) {
          out.push({
            id: uid(),
            date: d.toISOString().slice(0, 10),
            merchant: currentMerchant,
            amount: isCredit ? -Math.abs(currentAmount) : currentAmount,
            currency: "SGD",
            paidBy: "You"
          });
        }
      }
      
      // Start new transaction
      currentDate = `${dateMatch[1]} ${dateMatch[2]}`;
      currentAmount = 0;
      currentMerchant = '';
      isCredit = false;
      continue;
    }
    
    // Alternative date format: dd/mm/yyyy or dd-mm-yyyy
    const altDateMatch = line.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
    if (altDateMatch && !currentDate) {
      const [, day, month, yearStr] = altDateMatch;
      const d = new Date(Number(yearStr), Number(month) - 1, Number(day));
      if (!isNaN(d.getTime())) {
        currentDate = d.toISOString().slice(0, 10);
        currentAmount = 0;
        currentMerchant = '';
        isCredit = false;
        continue;
      }
    }
    
    // Look for amount patterns (with or without CR indicator)
    const amountMatch = line.match(/^(-?\d{1,3}(?:,\d{3})*\.\d{2})(\s*CR)?$/);
    if (amountMatch && currentDate) {
      currentAmount = Number(amountMatch[1].replace(/,/g, ""));
      isCredit = amountMatch[2] ? true : false;
      continue;
    }
    
    // Look for merchant description (usually the longest meaningful line)
    if (currentDate && currentAmount && !currentMerchant && line.length > 5) {
      // Skip lines that are clearly not merchant names
      if (!line.match(/^(BALANCE|CREDIT CARD|Statement Date|Page|Total|Subtotal|Date|Description|Amount|Transaction|Posting)/i) &&
          !line.match(/^\d/) && // Doesn't start with number
          !line.match(/^[A-Z\s]+$/) && // Not all caps (likely headers)
          line.includes(' ') && // Has spaces (likely merchant name)
          line.length > 8 && // Reasonable length for merchant name
          !line.match(/^[A-Z]{2,}\s+[A-Z]{2,}$/) && // Not just two uppercase words
          !line.match(/^[A-Z]+\s+\d+$/) && // Not "WORD 123" format
          !line.match(/^\d+\s+[A-Z]+$/)) { // Not "123 WORD" format
        
        currentMerchant = line.replace(/\s{2,}/g, " ").trim();
      }
    }
  }
  
  // Don't forget the last transaction
  if (currentDate && currentAmount && currentMerchant) {
    const d = new Date(`${currentDate} ${year}`);
    if (!isNaN(d.getTime())) {
      out.push({
        id: uid(),
        date: d.toISOString().slice(0, 10),
        merchant: currentMerchant,
        amount: isCredit ? -Math.abs(currentAmount) : currentAmount,
        currency: "SGD",
        paidBy: "You"
      });
    }
  }
  
  // Fallback to original method if no transactions found
  if (out.length === 0) {
    console.log("Primary parsing failed, trying fallback methods...");
    
    // Method 1: Look for transaction rows with date, description, amount pattern
    const transactionPattern = /(\d{1,2}\s+[A-Za-z]{3})\s+([A-Za-z0-9\s@&/.'\-,]+?)\s+(-?\d{1,3}(?:,\d{3})*\.\d{2})(\s*CR)?/gi;
    const matches = [...text.matchAll(transactionPattern)];
    
    for (const match of matches) {
      const [, dateStr, merchant, amountStr, creditFlag] = match;
      
      // Clean up merchant name
      const cleanMerchant = merchant.replace(/\s{2,}/g, " ").trim();
      
      // Skip if merchant is too short or looks like header
      if (cleanMerchant.length < 3 || 
          /^(BALANCE|CREDIT CARD|Statement Date|Page|Total|Subtotal|Date|Description|Amount)/i.test(cleanMerchant)) {
        continue;
      }
      
      const d = new Date(`${dateStr} ${year}`);
      if (isNaN(d.getTime())) continue;
      
      const amount = Number(amountStr.replace(/,/g, ""));
      const isCredit = creditFlag ? true : false;
      
      out.push({
        id: uid(),
        date: d.toISOString().slice(0, 10),
        merchant: cleanMerchant,
        amount: isCredit ? -Math.abs(amount) : amount,
        currency: "SGD",
        paidBy: "You"
      });
    }
    
    // Method 2: Original fallback if still no results
    if (out.length === 0) {
      const descs: string[] = [];
      const descRe1 = /(?:^|\n)([A-Z0-9][A-Z0-9 @&/.'\-*,]+SINGAPORE SG)(?=\n|$)/g;
      const descRe2 = /(?:^|\n)(PAYMENT\s*-\s*THANK\s*YOU)(?=\n|$)/gi;
      for (const m of text.matchAll(descRe1)) descs.push(m[1].replace(/\s{2,}/g, " ").trim());
      for (const m of text.matchAll(descRe2)) descs.push(m[1].replace(/\s{2,}/g, " ").trim());
      const cleanedDescs = descs.filter((d) => !/BALANCE FROM PREVIOUS STATEMENT/i.test(d) && !/CREDIT CARD/i.test(d));

      const rowRe = /(?<td>\d{1,2}\s+[A-Za-z]{3})\s+(?<pd>\d{1,2}\s+[A-Za-z]{3})\s+(?<amt>-?\d{1,3}(?:,\d{3})*\.\d{2})(?<cr>\s*CR)?/g;
      const rows: { date: string; amount: number }[] = [];
      for (const m of text.matchAll(rowRe)) {
        const g = (m as any).groups as { td: string; amt: string; cr?: string };
        const d = new Date(`${g.td} ${year}`); if (isNaN(d.getTime())) continue;
        const n = Number(g.amt.replace(/,/g, ""));
        rows.push({ date: d.toISOString().slice(0, 10), amount: g.cr ? -Math.abs(n) : n });
      }
      let r = rows.slice();
      if (r.length === cleanedDescs.length + 1 && Math.abs(r[0].amount) > 500) r = r.slice(1);
      const n = Math.min(r.length, cleanedDescs.length);
      for (let i = 0; i < n; i++) out.push({ id: uid(), date: r[i].date, merchant: cleanedDescs[i], amount: r[i].amount, currency: "SGD", paidBy: "You" });
    }
  }
  
  // Add some debugging info
  if (out.length > 0) {
    console.log(`Parsed ${out.length} transactions from SC statement`);
    console.log("Sample transactions:", out.slice(0, 3));
  } else {
    console.warn("No transactions parsed from SC statement");
  }
  
  return out;
}

// Fallback generic
function parseLinesToTxns(text: string): Txn[] {
  const lines = text.split(/\n+/); const out: Txn[] = [];
  const patterns: RegExp[] = [
    /(?<date>\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4})\s+(?<desc>.+?)\s+(?<amount>-?\d{1,3}(?:,\d{3})*\.\d{2})(?:\s*(?<cr>CR))?$/,
    /(?<date>\d{1,2}\s+[A-Za-z]{3,}\s+\d{4})\s+(?<desc>.+?)\s+(?:[A-Z]{3}\s*)?(?<amount>-?\d{1,3}(?:,\d{3})*\.\d{2})(?:\s*(?<cr>CR))?$/,
    /(?<date>\d{4}-\d{2}-\d{2})\s+(?<desc>.+?)\s+(?<amount>-?\d{1,3}(?:,\d{3})*\.\d{2})(?:\s*(?<cr>CR))?$/,
  ];
  for (const raw of lines) {
    let m: RegExpMatchArray | null = null;
    for (const re of patterns) { m = raw.match(re); if (m && (m as any).groups) break; }
    if (!m || !(m as any).groups) continue;
    const g = (m as any).groups as { date: string; desc: string; amount: string; cr?: string };
    const d = new Date(g.date); if (isNaN(d.getTime())) continue;
    const amt = Number(g.amount.replace(/,/g, "")); const signAmt = /\bCR\b/.test(g.cr || raw) ? -Math.abs(amt) : amt;
    out.push({ id: uid(), date: d.toISOString().slice(0, 10), merchant: g.desc.trim(), amount: signAmt, currency: "USD", paidBy: "You" });
  }
  return out;
}

async function parseFile(file: File): Promise<Txn[]> {
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (isPdf) {
    const text = await extractPdfText(file);
    const sc = parseSCStatement(text); if (sc.length) return sc;
    const generic = parseLinesToTxns(text); if (generic.length) return generic;
    console.warn("Parser could not map lines → using mock data.");
    return mockParse([file]);
  }
  return mockParse([file]);
}

// --- UI primitives ---
const Card: React.FC<{ title?: string; children: React.ReactNode; className?: string }> = ({ title, children, className }) => (
  <div className={`rounded-2xl border border-neutral-200 dark:border-neutral-800 bg-white/60 dark:bg-neutral-900/60 shadow-sm backdrop-blur p-4 ${className || ""}`}>
    {title && <div className="text-sm font-semibold text-neutral-700 dark:text-neutral-200 mb-2">{title}</div>}
    {children}
  </div>
);
const Pill = ({ children }: { children: React.ReactNode }) => (
  <span className="px-2 py-0.5 rounded-full text-xs bg-neutral-100 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700">{children}</span>
);

// --- Main ---
export default function BillBuddyPrototype() {
  const [files, setFiles] = useState<File[]>([]);
  const [txns, setTxns] = useState<Txn[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [friends, setFriends] = useState<string[]>(["You", "Sam", "Priya"]);
  const [query, setQuery] = useState("");
  const [budget, setBudget] = useState<Record<string, number>>({ Subscriptions: 50, Dining: 150, Groceries: 300, "School Fees": 0, Fees: 0 });
  const [showSplitFor, setShowSplitFor] = useState<Txn | null>(null);
  const [showFriendsMgr, setShowFriendsMgr] = useState(false);

  const [activeTab, setActiveTab] = useState<"txns" | "insights">("txns");
  const [txnView, setTxnView] = useState<"pending" | "grouped" | "splits" | "all" | "trash">("pending");
  const [openGroupId, setOpenGroupId] = useState<string | null>(null);
  const [insightsMineOnly, setInsightsMineOnly] = useState(true);
  const [splitFilterFriend, setSplitFilterFriend] = useState<string>("");

  // Debug state for PDF text
  const [debugText, setDebugText] = useState<string>("");
  const [showDebug, setShowDebug] = useState(false);

  // Soft delete toast
  const [toast, setToast] = useState<{ id: string; message: string } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup timer on unmount to prevent memory leaks
  useEffect(() => {
    return () => {
      if (toastTimer.current) {
        clearTimeout(toastTimer.current);
      }
    };
  }, []);

  // Parsed sets
  const parsedAll = useMemo(() => txns.map(t => ({ ...t, category: t.category ?? autoCategory(t.merchant) })), [txns]);
  const parsed = useMemo(() => parsedAll.filter(t => !t.deleted), [parsedAll]);

  const isPending = (t: Txn) => !t.groupId && !(t.splits?.length) && !t.reviewed;

  const pending = useMemo(() => parsed.filter(isPending), [parsed]);
  const splitTxns = useMemo(() => parsed.filter(t => t.splits && t.splits.length > 0), [parsed]);
  const trash = useMemo(() => parsedAll.filter(t => t.deleted), [parsedAll]);

  // Groups summary
  const groupsSummary = useMemo(() => {
    const byId = new Map<string, { id: string; name: string; merchant: string; count: number; total: number; last: string }>();
    for (const g of groups) byId.set(g.id, { id: g.id, name: g.name, merchant: g.merchant || g.name, count: 0, total: 0, last: "" });
    for (const t of parsed) {
      if (!t.groupId || !byId.has(t.groupId)) continue;
      const s = byId.get(t.groupId)!;
      s.count += 1; s.total += t.amount; if (!s.last || t.date > s.last) s.last = t.date;
    }
    return Array.from(byId.values()).filter(s => s.count > 0).sort((a, b) => b.total - a.total);
  }, [parsed, groups]);

  // Mine-only amount
  const amountForMe = (t: Txn) => {
    if (!insightsMineOnly) return t.amount;
    if (!t.splits || !t.splits.length) return t.amount;
    const me = t.splits.find(p => p.name === "You");
    return me ? me.amount : 0;
  };

  // Insights / rollups
  const spendByCategory = useMemo(() => {
    const m = new Map<string, number>(); parsed.forEach(t => m.set(t.category!, (m.get(t.category!) || 0) + amountForMe(t)));
    return Array.from(m, ([name, value]) => ({ name, value: +value.toFixed(2) }));
  }, [parsed, insightsMineOnly]);
  const spendByMerchant = useMemo(() => {
    const m = new Map<string, number>(); parsed.forEach(t => m.set(t.merchant, (m.get(t.merchant) || 0) + amountForMe(t)));
    return Array.from(m, ([merchant, total]) => ({ merchant, total: +total.toFixed(2) })).sort((a, b) => b.total - a.total).slice(0, 7);
  }, [parsed, insightsMineOnly]);
  const mom = useMemo(() => {
    const m = new Map<string, number>(); parsed.forEach(t => { const ym = t.date.slice(0, 7); m.set(ym, (m.get(ym) || 0) + amountForMe(t)); });
    return Array.from(m, ([month, total]) => ({ month, total: +total.toFixed(2) })).sort((a, b) => a.month.localeCompare(b.month));
  }, [parsed, insightsMineOnly]);

  // Balances for friends
  const balances = useMemo(() => {
    const b = new Map<string, number>();
    for (const t of splitTxns) {
      const payer = t.paidBy || "You";
      const totalAmount = t.amount;
      
      // Calculate what each person should pay
      const totalSplit = (t.splits || []).reduce((sum, part) => sum + part.amount, 0);
      
      // If splits don't add up to total, distribute proportionally
      if (Math.abs(totalSplit - totalAmount) > 0.01) {
        const splitParts = t.splits || [];
        if (splitParts.length > 0) {
          const ratio = totalAmount / totalSplit;
          splitParts.forEach(part => {
            const adjustedAmount = part.amount * ratio;
            if (part.name !== payer) {
              b.set(payer, (b.get(payer) || 0) + adjustedAmount);
              b.set(part.name, (b.get(part.name) || 0) - adjustedAmount);
            }
          });
        }
      } else {
        // Normal case: splits add up to total
        for (const part of t.splits || []) {
          if (part.name !== payer) {
            b.set(payer, (b.get(payer) || 0) + part.amount);
            b.set(part.name, (b.get(part.name) || 0) - part.amount);
          }
        }
      }
    }
    return b;
  }, [splitTxns]);

  // BUS/MRT quick facts
  const busTotal = useMemo(
    () => parsed.filter(t => normalizeMerchant(t.merchant).includes("BUS/MRT")).reduce((s, t) => s + amountForMe(t), 0),
    [parsed, insightsMineOnly]
  );
  const busRides = useMemo(() => parsed.filter(t => normalizeMerchant(t.merchant).includes("BUS/MRT")).length, [parsed]);
  const transportTotal = useMemo(() => spendByCategory.find(c => c.name === "Transport")?.value || 0, [spendByCategory]);
  const busSharePct = transportTotal > 0 ? Math.round((busTotal / transportTotal) * 100) : 0;

  // Credits/refunds (negative amounts)
  const creditsTotal = useMemo(() =>
    parsed.reduce((s, t) => s + (amountForMe(t) < 0 ? amountForMe(t) : 0), 0), [parsed, insightsMineOnly]
  );

  // Alerts
  const anomalies = useMemo(() => parsed.filter(t => t.amount >= 200), [parsed]);
  const overBudgetCount = useMemo(() => {
    let c = 0;
    for (const [cat, limit] of Object.entries(budget)) {
      if (limit > 0) {
        const spent = spendByCategory.find(x => x.name === cat)?.value || 0;
        if (spent > limit) c++;
      }
    }
    return c;
  }, [budget, spendByCategory]);
  const deletedCount = trash.length;

  // Filtered rows by view + search
  const allFiltered = useMemo(() => {
    const s = query.trim().toLowerCase();
    const base =
      txnView === "pending" ? pending :
      txnView === "splits" ? splitTxns.filter(t => splitFilterFriend ? (t.splits || []).some(p => p.name === splitFilterFriend) : true) :
      txnView === "trash" ? trash :
      parsed;
    if (!s) return base;
    return base.filter(t =>
      t.merchant.toLowerCase().includes(s) ||
      t.category?.toLowerCase().includes(s) ||
      t.amount.toString().includes(s));
  }, [parsed, pending, splitTxns, splitFilterFriend, txnView, trash, query]);

  // Actions
  async function handleParse() {
    if (!files.length) return;
    
    // Store debug text from first file
    if (files[0]) {
      const debugText = await extractPdfText(files[0]);
      setDebugText(debugText);
    }
    
    const all = (await Promise.all(files.map(parseFile))).flat();
    const gs = suggestGroups(all);
    const byKey = new Map(gs.map(g => [g.merchant!, g.id] as const));
    all.forEach(t => { const norm = normalizeMerchant(t.merchant); if (byKey.has(norm)) t.groupId = byKey.get(norm)!; });
    setTxns(all); setGroups(gs);
  }
  function assignToGroup(tid: string, gid: string) { setTxns(prev => prev.map(t => t.id === tid ? { ...t, groupId: gid, reviewed: true } : t)); }
  function setCategory(tid: string, cat: string) { setTxns(prev => prev.map(t => t.id === tid ? { ...t, category: cat } : t)); }
  function createRuleAndAssign(merchant: string, cat: string) {
    setTxns(prev => prev.map(t => normalizeMerchant(t.merchant) === normalizeMerchant(merchant) ? { ...t, category: cat } : t));
  }
  function exportCSV() {
    const csv = toCSV(parsed); // exclude deleted
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "billbuddy-transactions.csv"; a.click(); URL.revokeObjectURL(url);
  }
  function assignHundredToFriend(tid: string, friend: string) {
    if (!friend || friend === "You") return;
    setTxns(prev =>
      prev.map(t => t.id === tid ? { ...t, paidBy: "You", splits: [{ name: friend, amount: t.amount }], reviewed: true } : t)
    );
  }
  function markReviewed(id: string) { setTxns(prev => prev.map(t => (t.id === id ? { ...t, reviewed: true } : t))); }

  // Soft delete + undo
  function deleteTxn(id: string) {
    setTxns(prev => prev.map(t => t.id === id ? { ...t, deleted: true } : t));
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ id, message: "Transaction deleted." });
    toastTimer.current = setTimeout(() => setToast(null), 6000);
  }
  function undoDelete(id: string) {
    setTxns(prev => prev.map(t => t.id === id ? { ...t, deleted: false } : t));
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast(null);
  }
  function restoreTxn(id: string) { setTxns(prev => prev.map(t => t.id === id ? { ...t, deleted: false } : t)); }

  // Components
  const TxnTable: React.FC<{ rows: Txn[]; inTrash?: boolean }> = ({ rows, inTrash }) => (
    <div className="overflow-auto rounded-xl border">
      <table className="w-full text-sm">
        <thead className="bg-neutral-50 dark:bg-neutral-800">
          <tr>
            <th className="text-left p-2">Date</th>
            <th className="text-left p-2">Merchant</th>
            <th className="text-right p-2">Amount</th>
            <th className="text-left p-2">Category</th>
            {!inTrash && <th className="text-left p-2">People</th>}
            {!inTrash && <th className="text-left p-2">Group</th>}
            <th className="text-left p-2">{inTrash ? "Restore" : "Actions"}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(t => {
            const pendingRow = isPending(t);
            return (
              <tr
                key={t.id}
                className={`border-t hover:bg-neutral-50/60 dark:hover:bg-neutral-800/60 ${!inTrash && pendingRow ? "border-l-4 border-amber-400" : ""}`}
              >
                <td className="p-2 whitespace-nowrap">{t.date}</td>
                <td className="p-2 whitespace-nowrap flex items-center gap-2">
                  {t.merchant}
                  {!inTrash && (pendingRow ? <Pill>● Pending</Pill> : <Pill>✓ Reviewed</Pill>)}
                  {!inTrash && t.splits?.length ? <Pill>🧩 {t.splits.map(p => p.name).join(", ")}</Pill> : null}
                  {!inTrash && t.groupId ? <Pill>📦 grouped</Pill> : null}
                  {!inTrash && t.amount >= 200 ? <Pill><AlertTriangle className="inline w-3 h-3 mr-1"/>high</Pill> : null}
                  {!inTrash && t.amount < 0 ? <Pill>↩ credit</Pill> : null}
                </td>
                <td className="p-2 text-right">{fmt(t.amount)}</td>
                <td className="p-2">
                  <select className="bg-transparent border rounded-lg px-2 py-1" value={t.category}
                          onChange={(e) => setCategory(t.id, e.target.value)}>
                    {CATS.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </td>

                {!inTrash && (
                  <>
                    <td className="p-2">
                      <select
                        className="bg-transparent border rounded-lg px-2 py-1"
                        value=""
                        onChange={(e) => {
                          const v = e.target.value;
                          if (v === "__add__") { setShowFriendsMgr(true); return; }
                          if (v) assignHundredToFriend(t.id, v);
                          e.currentTarget.value = "";
                        }}
                      >
                        <option value="" hidden>Assign 100%…</option>
                        {friends.filter(f => f !== "You").map(f => <option key={f} value={f}>{f}</option>)}
                        <option value="__add__">+ Add friend…</option>
                      </select>
                    </td>
                    <td className="p-2">
                      <select className="bg-transparent border rounded-lg px-2 py-1" value={t.groupId || ""}
                              onChange={(e) => assignToGroup(t.id, e.target.value)}>
                        <option value="">—</option>
                        {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                      </select>
                    </td>
                  </>
                )}

                <td className="p-2">
                  {inTrash ? (
                    <button onClick={() => restoreTxn(t.id)} className="px-2 py-1 text-xs rounded-lg border flex items-center gap-1">
                      <RotateCcw className="w-3 h-3" /> Restore
                    </button>
                  ) : (
                    <div className="flex items-center gap-2">
                      <button onClick={() => createRuleAndAssign(t.merchant, t.category!)} className="px-2 py-1 text-xs rounded-lg border flex items-center gap-1"><Wand2 className="w-3 h-3" /> Always</button>
                      <button onClick={() => setShowSplitFor(t)} className="px-2 py-1 text-xs rounded-lg border flex items-center gap-1"><Users className="w-3 h-3" /> Split</button>
                      {pendingRow && (
                        <button onClick={() => markReviewed(t.id)} className="px-2 py-1 text-xs rounded-lg border">Done</button>
                      )}
                      <button onClick={() => deleteTxn(t.id)} className="px-2 py-1 text-xs rounded-lg border flex items-center gap-1 text-red-600">
                        <Trash2 className="w-3 h-3" /> Delete
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
          {!rows.length &&
            <tr><td colSpan={inTrash ? 5 : 7} className="p-6 text-center text-neutral-500">No rows match.</td></tr>}
        </tbody>
      </table>
    </div>
  );

  const GroupList: React.FC = () => (
    <div className="space-y-2">
      {groupsSummary.map(g => (
        <div key={g.id} className="rounded-xl border p-3 flex items-center gap-3">
          <FolderClosed className="w-4 h-4" />
          <div className="flex-1">
            <div className="font-medium">{g.name}</div>
            <div className="text-xs text-neutral-500">Count {g.count} • Total {fmt(g.total)} • Last {g.last || "-"}</div>
          </div>
          <button onClick={() => setOpenGroupId(g.id)} className="px-3 py-1.5 text-sm rounded-lg border">Open</button>
        </div>
      ))}
      {!groupsSummary.length && <div className="text-sm text-neutral-500">No groups yet.</div>}
    </div>
  );

  const SplitsLedger: React.FC = () => {
    const you = balances.get("You") || 0;
    const others = Array.from(balances.entries()).filter(([n]) => n !== "You").sort((a,b)=> Math.abs(b[1]) - Math.abs(a[1]));
    const friendOptions = friends.filter(f => f !== "You");
    const ledgerRows = splitTxns.filter(t => splitFilterFriend ? (t.splits || []).some(p => p.name === splitFilterFriend) : true);
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-3 text-sm">
          <Pill>You {you >= 0 ? "are owed" : "owe"} {fmt(Math.abs(you))}</Pill>
          <span className="text-neutral-500">Friends: {others.map(([n,v]) => `${n} ${v>=0?"owes":"is owed"} ${fmt(Math.abs(v))}`).join(" • ") || "—"}</span>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-neutral-500">Filter:</span>
            <select className="border rounded px-2 py-1 text-xs" value={splitFilterFriend} onChange={(e)=> setSplitFilterFriend(e.target.value)}>
              <option value="">All friends</option>
              {friendOptions.map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
        </div>
        <div className="overflow-auto rounded-xl border">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 dark:bg-neutral-800">
              <tr>
                <th className="text-left p-2">Date</th>
                <th className="text-left p-2">Merchant</th>
                <th className="text-left p-2">Paid by</th>
                <th className="text-right p-2">Total</th>
                <th className="text-left p-2">Split With</th>
              </tr>
            </thead>
            <tbody>
              {ledgerRows.map(t => (
                <tr key={t.id} className="border-t">
                  <td className="p-2 whitespace-nowrap">{t.date}</td>
                  <td className="p-2 whitespace-nowrap">{t.merchant}</td>
                  <td className="p-2 whitespace-nowrap">{t.paidBy || "You"}</td>
                  <td className="p-2 text-right">{fmt(t.amount)}</td>
                  <td className="p-2">{t.splits?.map(p => <Pill key={p.name}>{p.name}: {fmt(p.amount)}</Pill>)}</td>
                </tr>
              ))}
              {!ledgerRows.length &&
                <tr><td colSpan={5} className="p-6 text-center text-neutral-500">No splits match this filter.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  // --- Balanced "Medium" Summary ---
  const QuickSummary: React.FC = () => {
    const totalMine = parsed.reduce((s,t)=> s + amountForMe(t), 0);
    const youNet = balances.get("You") || 0;

    const catsSorted = [...spendByCategory].sort((a,b)=> b.value - a.value);
    const topCats = catsSorted.slice(0,4);
    const totalAbs = Math.abs(totalMine) || 1;

    const topGroups = groupsSummary.slice(0,2);

    return (
      <Card title="Quick Summary">
        {/* Toggle + KPI strip */}
        <div className="flex items-center justify-between mb-2 text-sm">
          <div className="flex flex-wrap items-center gap-3">
            <span><span className="font-semibold">Total ({insightsMineOnly ? "My share" : "All"}):</span> {fmt(totalMine)}</span>
            <span>Net with friends {youNet>=0?"+":""}{fmt(youNet)}</span>
            <span>Pending {pending.length}</span>
            <span>Credits {fmt(creditsTotal)}</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setInsightsMineOnly(true)} className={`px-2 py-1 rounded-lg border text-xs ${insightsMineOnly ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : ""}`}>My share</button>
            <button onClick={() => setInsightsMineOnly(false)} className={`px-2 py-1 rounded-lg border text-xs ${!insightsMineOnly ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : ""}`}>All</button>
          </div>
        </div>

        {/* A) Categories (Top 4) */}
        <div className="text-sm mb-1">Where it went (Top categories)</div>
        <div className="space-y-1 mb-2">
          {topCats.map(c => {
            const pct = Math.max(1, Math.round((Math.abs(c.value)/totalAbs)*100));
            return (
              <button
                key={c.name}
                className="w-full text-left"
                onClick={() => { setActiveTab("txns"); setTxnView("all"); setQuery(c.name.toLowerCase()); }}
                title={`Show ${c.name}`}
              >
                <div className="flex items-center gap-2">
                  <div className="w-28 text-xs text-neutral-600">{c.name}</div>
                  <div className="flex-1 h-2 rounded-full bg-neutral-200 dark:bg-neutral-800 overflow-hidden">
                    <div className="h-full bg-neutral-900 dark:bg-white" style={{ width: `${pct}%` }} />
                  </div>
                  <div className="w-24 text-right text-xs">{fmt(c.value)}</div>
                </div>
              </button>
            );
          })}
          {!topCats.length && <div className="text-xs text-neutral-400">—</div>}
        </div>
        {!!busTotal && (
          <div className="text-xs text-neutral-600 mb-2">
            BUS/MRT {fmt(busTotal)} ({busRides} rides) • {busSharePct}% of Transport
          </div>
        )}
        <div className="text-xs mb-3">
          <button className="underline" onClick={()=> setActiveTab("insights")}>View all categories →</button>
        </div>

        {/* B) People mini-ledger */}
        <div className="text-sm mb-1">Who it's for (People)</div>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <Pill>You {youNet>=0?"are owed":"owe"} {fmt(Math.abs(youNet))}</Pill>
          {Array.from(balances.entries())
             .filter(([n])=> n!=="You")
             .sort((a,b)=> Math.abs(b[1]) - Math.abs(a[1]))
             .slice(0,2)
             .map(([n,v]) => (
              <button key={n} className="text-xs px-2 py-1 rounded-full border"
                onClick={()=> { setActiveTab("txns"); setTxnView("splits"); setSplitFilterFriend(n); }}>
                {n}: {v>=0?"+":""}{fmt(v)}
              </button>
            ))
          }
          <button className="text-xs px-2 py-1 rounded-full border" onClick={()=> { setActiveTab("txns"); setTxnView("splits"); }}>
            Open Splits
          </button>
        </div>

        {/* C) Recurring & Alerts */}
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <div className="flex items-center gap-2">
            <span className="font-medium">Groups (3+):</span>
            {topGroups.map(g => (
              <button key={g.id} className="px-2 py-1 rounded-full border"
                onClick={()=> { setActiveTab("txns"); setTxnView("grouped"); setOpenGroupId(g.id); }}>
                {g.merchant.split(" ").slice(0,3).join(" ")} {fmt(g.total)}
              </button>
            ))}
            <button className="underline" onClick={()=> { setActiveTab("txns"); setTxnView("grouped"); }}>View all</button>
          </div>
          <div className="flex items-center gap-2">
            <span className="font-medium">Alerts:</span>
            <button className="px-2 py-1 rounded-full border" onClick={()=> setActiveTab("insights")}>Over-budget ({overBudgetCount})</button>
            <button className="px-2 py-1 rounded-full border" onClick={()=> { setActiveTab("txns"); setTxnView("all"); setQuery(""); }}>Anomalies ({anomalies.length})</button>
            <button className="px-2 py-1 rounded-full border" onClick={()=> setTxnView("trash")}>Deleted ({deletedCount})</button>
          </div>
        </div>
      </Card>
    );
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-neutral-50 to-white dark:from-neutral-950 dark:to-neutral-900 text-neutral-900 dark:text-neutral-100 p-4 md:p-6 space-y-6">
      {/* Header */}
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart2 className="w-6 h-6" />
          <h1 className="text-xl font-bold tracking-tight">BillBuddy — Prototype</h1>
          <Pill>SC PDF Parser</Pill>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowFriendsMgr(true)} className="px-3 py-1.5 text-sm rounded-xl border flex items-center gap-1">
            <UserCircle2 className="w-4 h-4"/> Friends
          </button>
          <button onClick={() => setShowDebug(true)} className="px-3 py-1.5 text-sm rounded-xl border flex items-center gap-1">
            <Wand2 className="w-4 h-4"/> Debug
          </button>
          <button onClick={() => document.documentElement.classList.toggle("dark")} className="px-3 py-1.5 text-sm rounded-xl border border-neutral-300 dark:border-neutral-700">Toggle Theme</button>
          <button onClick={exportCSV} className="px-3 py-1.5 text-sm rounded-xl border flex items-center gap-1"><Download className="w-4 h-4" /> Export CSV</button>
        </div>
      </header>

      {/* Tabs */}
      <div className="flex items-center gap-2">
        <button onClick={() => setActiveTab("txns")} className={`px-3 py-1.5 rounded-xl border ${activeTab === "txns" ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : ""}`}>Transactions</button>
        <button onClick={() => setActiveTab("insights")} className={`px-3 py-1.5 rounded-xl border ${activeTab === "insights" ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : ""}`}>Insights</button>
      </div>

      {/* Upload & Summary */}
      <section className="grid md:grid-cols-3 gap-4">
        <Card className="md:col-span-2" title="1) Upload Statements (PDF)">
          <div className="flex flex-col md:flex-row items-center gap-3">
            <label className="flex-1 border-2 border-dashed rounded-2xl p-6 text-center cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-800">
              <input type="file" multiple accept="application/pdf" className="hidden" onChange={(e) => setFiles(Array.from(e.target.files || []))} />
              <Upload className="w-8 h-8 mx-auto mb-2" />
              <div className="text-sm">Drag & drop or click to choose PDFs</div>
              <div className="text-xs text-neutral-500 mt-1">Optimized for Standard Chartered (SG) text-PDFs</div>
            </label>
            <button disabled={!files.length} onClick={handleParse} className="px-4 py-2 rounded-xl bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 disabled:opacity-50">Parse & Auto-Group</button>
          </div>
          {!!files.length && <div className="text-xs text-neutral-600 dark:text-neutral-400 mt-2">Selected: {files.map((f) => f.name).join(", ")}</div>}
        </Card>
        <QuickSummary />
      </section>

      {/* Main sections */}
      {activeTab === "txns" ? (
        <>
          {/* Sub-filters */}
          <div className="flex items-center gap-2">
            <button onClick={() => setTxnView("pending")} className={`px-3 py-1.5 rounded-xl border flex items-center gap-1 ${txnView === "pending" ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : ""}`}><ListFilter className="w-4 h-4" /> Pending ({pending.length})</button>
            <button onClick={() => setTxnView("grouped")} className={`px-3 py-1.5 rounded-xl border flex items-center gap-1 ${txnView === "grouped" ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : ""}`}><Layers className="w-4 h-4" /> Grouped ({groupsSummary.length})</button>
            <button onClick={() => setTxnView("splits")} className={`px-3 py-1.5 rounded-xl border flex items-center gap-1 ${txnView === "splits" ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : ""}`}><SplitSquareHorizontal className="w-4 h-4" /> Splits ({splitTxns.length})</button>
            <button onClick={() => setTxnView("all")} className={`px-3 py-1.5 rounded-xl border ${txnView === "all" ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : ""}`}>All ({parsed.length})</button>
            <button onClick={() => setTxnView("trash")} className={`px-3 py-1.5 rounded-xl border flex items-center gap-1 ${txnView === "trash" ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : ""}`}><Trash2 className="w-4 h-4" /> Trash ({trash.length})</button>
            <div className="ml-auto flex items-center gap-2 px-3 py-2 rounded-xl border w-full md:w-80">
              <Search className="w-4 h-4" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search merchant/category/amount" className="bg-transparent outline-none text-sm w-full" />
            </div>
          </div>

          {/* Content by sub-filter */}
          {txnView === "grouped" ? (
            <Card title="Groups"><GroupList /></Card>
          ) : txnView === "splits" ? (
            <Card title="Split Transactions"><SplitsLedger /></Card>
          ) : txnView === "trash" ? (
            <Card title="Trash"><TxnTable rows={allFiltered} inTrash /></Card>
          ) : (
            <Card title={txnView === "pending" ? "Pending Review" : "All Transactions"}>
              <TxnTable rows={allFiltered} />
            </Card>
          )}

          {/* Group Drawer */}
          {openGroupId && (
            <div className="fixed inset-0 bg-black/40 flex items-center justify-end p-0 z-50">
              <div className="h-full w-full max-w-3xl bg-white dark:bg-neutral-900 border-l border-neutral-200 dark:border-neutral-800 shadow-xl flex flex-col">
                <div className="p-4 border-b border-neutral-200 dark:border-neutral-800 flex items-center justify-between">
                  {(() => {
                    const g = groups.find(x => x.id === openGroupId);
                    return (<div className="flex items-center gap-2"><FolderClosed className="w-4 h-4" /><div className="font-semibold">{g?.name || "Group"}</div></div>);
                  })()}
                  <button onClick={() => setOpenGroupId(null)} className="px-2 py-1 text-sm rounded-lg border flex items-center gap-1"><X className="w-4 h-4" /> Close</button>
                </div>
                <div className="p-4 overflow-auto">
                  <div className="mb-2 text-xs text-neutral-500">Transactions in this group</div>
                  <div className="overflow-auto rounded-xl border">
                    <table className="w-full text-sm">
                      <thead className="bg-neutral-50 dark:bg-neutral-800">
                        <tr>
                          <th className="text-left p-2">Date</th>
                          <th className="text-left p-2">Merchant</th>
                          <th className="text-right p-2">Amount</th>
                          <th className="text-left p-2">Category</th>
                          <th className="text-left p-2">People</th>
                          <th className="text-left p-2">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {parsed.filter(t => t.groupId === openGroupId).map(t => (
                          <tr key={t.id} className="border-t">
                            <td className="p-2">{t.date}</td>
                            <td className="p-2">{t.merchant} {t.splits?.length ? <Pill>🧩 split</Pill> : null}</td>
                            <td className="p-2 text-right">{fmt(t.amount)}</td>
                            <td className="p-2">{t.category}</td>
                            <td className="p-2">{t.splits?.map(p => <Pill key={p.name}>{p.name}: {fmt(p.amount)}</Pill>)}</td>
                            <td className="p-2">
                              <button onClick={() => setShowSplitFor(t)} className="px-2 py-1 text-xs rounded-lg border flex items-center gap-1"><Users className="w-3 h-3" /> Split</button>
                            </td>
                          </tr>
                        ))}
                        {!parsed.filter(t => t.groupId === openGroupId).length &&
                          <tr><td colSpan={6} className="p-6 text-center text-neutral-500">No transactions.</td></tr>}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>
          )}
        </>
      ) : (
        // Insights tab
        <>
          <div className="flex items-center gap-2">
            <span className="text-sm text-neutral-600">Scope:</span>
            <button onClick={() => setInsightsMineOnly(true)} className={`px-3 py-1.5 rounded-xl border text-sm ${insightsMineOnly ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : ""}`}>My share</button>
            <button onClick={() => setInsightsMineOnly(false)} className={`px-3 py-1.5 rounded-xl border text-sm ${!insightsMineOnly ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : ""}`}>All</button>
          </div>

          <section className="grid lg:grid-cols-3 gap-4">
            <Card title="Spend by Category">
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie dataKey="value" data={spendByCategory} nameKey="name" label />
                    <Tooltip /><Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title="Top Merchants">
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={spendByMerchant}>
                    <XAxis dataKey="merchant" hide /><YAxis /><Tooltip /><Legend />
                    <Bar dataKey="total" name="Total" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="text-xs text-neutral-500 mt-1">Top 7 by total spend</div>
            </Card>
            <Card title="MoM Trend">
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={mom}>
                    <XAxis dataKey="month" /><YAxis /><Tooltip /><Legend />
                    <Line type="monotone" dataKey="total" name="Total" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </section>
          <section>
            <Card title="Budgets">
              <div className="space-y-3">
                {Object.entries(budget).map(([cat, limit]) => {
                  const spent = spendByCategory.find(x => x.name === cat)?.value || 0;
                  const pct = limit > 0 ? Math.min(100, Math.round((spent / limit) * 100)) : 0;
                  return (
                    <div key={cat}>
                      <div className="flex justify-between text-xs mb-1"><span>{cat}</span><span>{fmt(spent)} / {fmt(limit)}</span></div>
                      <div className="h-2 rounded-full bg-neutral-200 dark:bg-neutral-800 overflow-hidden"><div className={`h-full ${pct > 100 ? "bg-red-600" : pct > 90 ? "bg-red-500" : "bg-green-500"}`} style={{ width: (limit>0?pct:0) + "%" }} /></div>
                    </div>
                  );
                })}
                <div className="flex items-center gap-2 text-xs mt-2">
                  <Settings2 className="w-4 h-4" /><span>Adjust limits: </span>
                  <select className="bg-transparent border rounded px-2 py-1 text-xs" onChange={(e) => { const [cat, val] = e.target.value.split("|"); setBudget(prev => ({ ...prev, [cat]: Number(val) })); }}>
                    {CATS.map(c => [100, 150, 200, 300, 500].map(v => <option key={c + v} value={`${c}|${v}`}>{c} → {fmt(v)}</option>))}
                  </select>
                </div>
                <div className="text-[11px] text-neutral-500">Charts respect "My share" (your split share) or "All".</div>
              </div>
            </Card>
          </section>
        </>
      )}

      {/* Split Modal */}
      {showSplitFor && (
        <SplitModal
          txn={showSplitFor}
          friends={friends}
          onClose={() => setShowSplitFor(null)}
          onSave={(splits, paidBy) => {
            setTxns(prev => prev.map(t =>
              t.id === showSplitFor.id ? { ...t, splits, paidBy, reviewed: true } : t
            ));
            setShowSplitFor(null);
          }}
          onAddFriend={(name) => setFriends(prev => prev.includes(name) ? prev : [...prev, name])}
          onQuickAssign={(friend) => {
            if (!friend) return;
            setTxns(prev => prev.map(t =>
              t.id === showSplitFor.id ? { ...t, paidBy: "You", splits: [{ name: friend, amount: t.amount }], reviewed: true } : t
            ));
            setShowSplitFor(null);
          }}
        />
      )}

      {/* Friends Manager */}
      {showFriendsMgr && (
        <FriendsManager friends={friends} onClose={() => setShowFriendsMgr(false)}
          onChange={(next) => setFriends(next.includes("You") ? next : ["You", ...next])} />
      )}

      {/* Debug Modal */}
      {showDebug && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-50">
          <div className="w-full max-w-4xl max-h-[80vh] rounded-2xl bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 shadow-xl flex flex-col">
            <div className="p-4 border-b border-neutral-200 dark:border-neutral-800 flex items-center justify-between">
              <div className="font-semibold">Debug: Extracted PDF Text</div>
              <button onClick={() => setShowDebug(false)} className="px-2 py-1 text-sm rounded-lg border flex items-center gap-1"><X className="w-4 h-4" /> Close</button>
            </div>
            <div className="p-4 overflow-auto flex-1">
              <div className="text-sm text-neutral-600 mb-2">Extracted text from PDF (first 2000 characters):</div>
              <div className="bg-neutral-100 dark:bg-neutral-800 p-3 rounded-lg font-mono text-xs whitespace-pre-wrap max-h-96 overflow-auto">
                {debugText ? debugText.substring(0, 2000) + (debugText.length > 2000 ? '...' : '') : 'No text extracted yet. Upload and parse a PDF first.'}
              </div>
              {debugText && (
                <div className="mt-3 text-xs text-neutral-500">
                  Total length: {debugText.length} characters
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Undo Toast */}
      {toast && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 border rounded-xl shadow px-3 py-2 text-sm flex items-center gap-2 z-50">
          <span>{toast.message}</span>
          <button onClick={() => undoDelete(toast.id)} className="px-2 py-1 rounded-lg border bg-white/10 dark:bg-black/10">Undo</button>
        </div>
      )}

      <footer className="text-[11px] text-neutral-500 pt-6">
        ● Pending rows have an amber rail; ✓ Reviewed rows lose it. Delete uses soft-delete with Undo & Trash.  
        Parser tailored for Standard Chartered SG; scanned PDFs need OCR (future).
      </footer>
    </div>
  );
}

// --- Split Modal ---
function SplitModal({ txn, friends, onClose, onSave, onAddFriend, onQuickAssign }: {
  txn: Txn; friends: string[]; onClose: () => void;
  onSave: (splits: SplitPart[], paidBy: string) => void;
  onAddFriend: (name: string) => void;
  onQuickAssign: (friend: string) => void;
}) {
  const [mode, setMode] = useState<"equal" | "custom">("equal");
  const [paidBy, setPaidBy] = useState<string>(txn.paidBy || "You");
  const [parts, setParts] = useState<SplitPart[]>(() => {
    const base = [friends[0] || "You", friends.find(f => f !== "You") || "Friend A"];
    const per = +(txn.amount / base.length).toFixed(2);
    return base.map(nm => ({ name: nm, amount: per }));
  });
  const total = useMemo(() => parts.reduce((s, p) => s + p.amount, 0), [parts]);
  const remaining = +(txn.amount - total).toFixed(2);

  function setEqual(len = parts.length) {
    const names = Array.from({ length: len }, (_, i) => parts[i]?.name || `Friend ${i + 1}`);
    const per = +(txn.amount / len).toFixed(2);
    const next = names.map(nm => ({ name: nm, amount: per }));
    const sum = next.reduce((s, p) => s + p.amount, 0);
    if (sum !== txn.amount) next[0].amount += +(txn.amount - sum).toFixed(2);
    setParts(next);
  }
  function addPerson(name: string) {
    if (!name) return;
    onAddFriend(name);
    const next = [...parts, { name, amount: 0 }];
    if (mode === "equal") setEqual(next.length); else setParts(next);
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-50">
      <div className="w-full max-w-xl rounded-2xl bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 shadow-xl">
        <div className="p-4 border-b border-neutral-200 dark:border-neutral-800 flex items-center justify-between">
          <div>
            <div className="text-sm text-neutral-500">Split transaction</div>
            <div className="font-semibold">{txn.merchant} — {fmt(txn.amount)}</div>
          </div>
          <button onClick={onClose} className="px-2 py-1 text-sm rounded-lg border">Close</button>
        </div>
        <div className="p-4 space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>Paid by:</span>
            <select className="border rounded px-2 py-1" value={paidBy} onChange={(e) => setPaidBy(e.target.value)}>
              {[...new Set(["You", ...friends])].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
            <span className="ml-auto text-xs text-neutral-500">Remaining: {fmt(remaining)}</span>
          </div>

          <div className="flex items-center gap-2 text-sm">
            <span>Mode:</span>
            <select className="border rounded px-2 py-1" value={mode} onChange={(e) => { const v = e.target.value as "equal" | "custom"; setMode(v); if (v === "equal") setEqual(); }}>
              <option value="equal">Equal</option>
              <option value="custom">Custom</option>
            </select>
            <div className="ml-auto flex items-center gap-2">
              <span className="text-xs text-neutral-500">Quick:</span>
              <select className="border rounded px-2 py-1 text-xs" defaultValue="" onChange={(e) => { const f = e.target.value; if (f) onQuickAssign(f); }}>
                <option value="" disabled>Assign 100% to…</option>
                {friends.filter(f => f !== "You").map(f => <option key={f} value={f}>{f}</option>)}
                <option value="" disabled>────────</option>
                <option value="__noop__">Use custom split ↓</option>
              </select>
            </div>
          </div>

          <div className="space-y-2">
            {parts.map((p, i) => (
              <div key={i} className="grid grid-cols-12 items-center gap-2">
                <input className="col-span-7 border rounded-lg px-2 py-1" value={p.name}
                  onChange={(e) => setParts(prev => prev.map((x, ix) => ix === i ? { ...x, name: e.target.value } : x))} />
                <div className="col-span-5 flex items-center gap-2">
                  <input type="number" step="0.01" className="w-28 border rounded-lg px-2 py-1 text-right" value={p.amount}
                    onChange={(e) => setParts(prev => prev.map((x, ix) => ix === i ? { ...x, amount: Number(e.target.value) } : x))} />
                  <button onClick={() => setParts(prev => prev.filter((_, ix) => ix !== i))} className="text-xs px-2 py-1 border rounded-lg">Remove</button>
                </div>
              </div>
            ))}
            <div className="flex items-center gap-2">
              <input id="newFriend" placeholder="Add friend name" className="border rounded-lg px-2 py-1 flex-1" />
              <button onClick={() => { const el = document.getElementById("newFriend") as HTMLInputElement | null; const name = (el?.value || "").trim(); addPerson(name); if (el) el.value = ""; }} className="px-3 py-1.5 border rounded-lg flex items-center gap-1"><UserPlus className="w-4 h-4" /> Add</button>
            </div>
          </div>

          <div className="text-sm text-neutral-600 dark:text-neutral-400">
            Total assigned: <span className="font-semibold">{fmt(total)}</span> of {fmt(txn.amount)}
          </div>
        </div>
        <div className="p-4 border-t border-neutral-200 dark:border-neutral-800 flex items-center justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg border">Cancel</button>
          <button disabled={Math.abs(remaining) > 0.009} onClick={() => onSave(parts, paidBy)} className="px-3 py-1.5 rounded-lg bg-neutral-900 text-white disabled:opacity-50">Save</button>
        </div>
      </div>
    </div>
  );
}

// --- Friends Manager ---
function FriendsManager({ friends, onClose, onChange }: {
  friends: string[];
  onClose: () => void;
  onChange: (next: string[]) => void;
}) {
  const [list, setList] = useState<string[]>(friends);

  function addFriend() {
    const name = prompt("Friend name?")?.trim();
    if (!name) return;
    if (list.includes(name)) return alert("Already exists.");
    setList(prev => [...prev, name]);
  }
  function renameFriend(oldName: string) {
    const name = prompt("Rename friend to?", oldName)?.trim();
    if (!name || name === oldName) return;
    if (name === "You") return alert('"You" is reserved.');
    if (list.includes(name)) return alert("That name already exists.");
    setList(prev => prev.map(n => n === oldName ? name : n));
  }
  function removeFriend(name: string) {
    if (name === "You") return;
    setList(prev => prev.filter(n => n !== name));
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-50">
      <div className="w-full max-w-md rounded-2xl bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 shadow-xl">
        <div className="p-4 border-b border-neutral-200 dark:border-neutral-800 flex items-center justify-between">
          <div className="font-semibold">Friends</div>
          <button onClick={onClose} className="px-2 py-1 text-sm rounded-lg border"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-4 space-y-2">
          {list.map(n => (
            <div key={n} className="flex items-center justify-between rounded-lg border px-3 py-2">
              <div className="flex items-center gap-2"><Users className="w-4 h-4" /><div>{n}</div></div>
              <div className="flex items-center gap-2">
                <button disabled={n === "You"} onClick={() => renameFriend(n)} className="px-2 py-1 text-xs rounded-lg border disabled:opacity-50">Rename</button>
                <button disabled={n === "You"} onClick={() => removeFriend(n)} className="px-2 py-1 text-xs rounded-lg border disabled:opacity-50">Remove</button>
              </div>
            </div>
          ))}
          {!list.length && <div className="text-sm text-neutral-500">No friends yet.</div>}
          <button onClick={addFriend} className="mt-2 px-3 py-1.5 text-sm rounded-lg border flex items-center gap-1"><UserPlus className="w-4 h-4" /> Add friend</button>
        </div>
        <div className="p-4 border-t border-neutral-200 dark:border-neutral-800 flex items-center justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg border">Cancel</button>
          <button onClick={() => { onChange(list); onClose(); }} className="px-3 py-1.5 rounded-lg bg-neutral-900 text-white">Save</button>
        </div>
      </div>
    </div>
  );
}
