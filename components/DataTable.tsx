'use client';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { motion } from 'framer-motion';
import type { DataTableProps, DataTableColumn } from '@/type';

const getValueByPath = (obj: unknown, path: string): unknown => {
  if (path === '__index__') {
    return undefined;
  }
  return path.split('.').reduce<unknown>((current, prop) => {
    if (current && typeof current === 'object' && prop in current) {
      return (current as Record<string, unknown>)[prop];
    }
    return undefined;
  }, obj);
};

const DataTable = <T,>({
  columns,
  data,
  rowKey,
  tableClassName,
  headerClassName,
  headerRowClassName,
  headerCellClassName,
  bodyRowClassName,
  bodyCellClassName,
}: DataTableProps<T>) => {
  const getKey = (row: T, index: number): React.Key => {
    if (typeof rowKey === 'string') {
      if (rowKey === '__index__') {
        return index;
      }
      const key = getValueByPath(row, rowKey);
      return key !== undefined ? String(key) : index;
    }
    return rowKey(row, index);
  };

  return (
    <Table className={cn('custom-scrollbar', tableClassName)}>
      <TableHeader className={headerClassName}>
        <TableRow className={cn('hover:bg-transparent!', headerRowClassName)}>
          {columns.map((column: DataTableColumn<T>, i: number) => (
            <TableHead
              key={i}
              className={cn(
                'bg-dark-400 text-purple-100 py-4 first:pl-5 last:pr-5',
                headerCellClassName,
                column.headClassName,
              )}
            >
              {column.header}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((row: T, rowIndex: number) => (
          <motion.tr
            key={getKey(row, rowIndex)}
            className={cn(
              'overflow-hidden rounded-lg border-b border-purple-100/5 relative',
              bodyRowClassName,
            )}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, delay: rowIndex * 0.02 }}
            whileHover={{
              y: -2,
              transition: { duration: 0.2, ease: 'easeOut' },
            }}
            style={{
              boxShadow: '0 0 0 rgba(0, 0, 0, 0)',
            }}
            onHoverStart={(e) => {
              const target = e.currentTarget as HTMLTableRowElement;
              if (target) {
                target.style.boxShadow = '0 4px 12px rgba(139, 92, 246, 0.15)';
                target.style.backgroundColor = 'rgba(30, 41, 59, 0.5)';
              }
            }}
            onHoverEnd={(e) => {
              const target = e.currentTarget as HTMLTableRowElement;
              if (target) {
                target.style.boxShadow = '0 0 0 rgba(0, 0, 0, 0)';
                target.style.backgroundColor = '';
              }
            }}
          >
            {columns.map((column: DataTableColumn<T>, columnIndex: number) => (
              <TableCell
                key={columnIndex}
                className={cn('py-4 first:pl-5 last:pr-5', bodyCellClassName, column.cellClassName)}
              >
                {column.cell(row, rowIndex)}
              </TableCell>
            ))}
          </motion.tr>
        ))}
      </TableBody>
    </Table>
  );
};

export default DataTable;
