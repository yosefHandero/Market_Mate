'use client';

import Link from 'next/link';
import Image from 'next/image';
import { cn, formatCurrency, formatPercentage } from '@/lib/utils';
import { TrendingDown, TrendingUp } from 'lucide-react';
import DataTable from '@/components/DataTable';
import { TrendingCoin } from '@/type';

interface TrendingCoinsTableProps {
  coins: TrendingCoin[];
}

export default function TrendingCoinsTable({ coins }: TrendingCoinsTableProps) {
  const columns: DataTableColumn<TrendingCoin>[] = [
    {
      header: 'Name',
      cellClassName: 'name-cell',
      cell: (coin) => {
        const item = coin.item;

        return (
          <Link href={`/coins/${item.id}`}>
            <Image src={item.large} alt={item.name} width={36} height={36} />
            <p>{item.name}</p>
          </Link>
        );
      },
    },
    {
      header: '24h Change',
      cellClassName: 'change-cell',
      cell: (coin) => {
        const item = coin.item;
        const isTrendingUp = item.data.price_change_percentage_24h.usd > 0;

        return (
          <div className={cn('price-change', isTrendingUp ? 'text-green-500' : 'text-red-500')}>
            <p className="flex items-center">
              {formatPercentage(item.data.price_change_percentage_24h.usd)}
              {isTrendingUp ? (
                <TrendingUp width={16} height={16} />
              ) : (
                <TrendingDown width={16} height={16} />
              )}
            </p>
          </div>
        );
      },
    },
    {
      header: 'Price',
      cellClassName: 'price-cell',
      cell: (coin) => formatCurrency(coin.item.data.price),
    },
  ];

  return (
    <DataTable
      data={coins.slice(0, 6) || []}
      columns={columns}
      rowKey="item.id"
      tableClassName="trending-coins-table"
      headerCellClassName="py-3!"
      bodyCellClassName="py-2!"
    />
  );
}
