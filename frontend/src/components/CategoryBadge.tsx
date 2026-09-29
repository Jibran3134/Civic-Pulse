import React from 'react'
import { Droplets, Zap, Trash2, Milestone, Lightbulb, HelpCircle } from 'lucide-react'
import { Category } from '../types'

interface CategoryBadgeProps {
  category: Category
}

export const CategoryBadge: React.FC<CategoryBadgeProps> = ({ category }) => {
  const getIcon = () => {
    switch (category) {
      case 'water':
        return <Droplets size={12} />
      case 'electricity':
        return <Zap size={12} />
      case 'sanitation':
        return <Trash2 size={12} />
      case 'roads':
        return <Milestone size={12} />
      case 'streetlights':
        return <Lightbulb size={12} />
      case 'other':
      default:
        return <HelpCircle size={12} />
    }
  }

  return (
    <span className={`badge badge-category badge-${category}`}>
      {getIcon()}
      <span>{category.toUpperCase()}</span>
    </span>
  )
}
